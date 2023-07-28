"""
COORDINATOR CLASS 
    This is the class that serves as an interface between the server (web_app.py) and the motor system comprised of all of the other classes that 
    regulate in one way or another the operation of the OT2 motors.
    There are 6 main blocks of code that implement the basic functionalities of the motor system:

    I. Manual Control
        This section takes care of opening a separate thread that "listens" to the inputs the user provides through the joystick, while the main thread
        executes in an infinite loop any methods associated to the inputs received on the joystick. The infinite loop running on the main thread stops 
        when the "listening" of the joystick is terminated, which can happen whenever the stop_listen() method is called within the joystick or by
        calling the stop_manual_control() method from within Coordinator (found in this section).

    II. Instantaneous Commands
        This section provides the ability to move the motors to any location recognized either as a well or pot in the system. There is a common method 
        called by both procedures called go_to_position() which only receives an x, y, z coordinate as input and goes there with the motors. Therefore,
        the other methods just take care of obtaining the x,y,z coordinate for the specified well or pot and then call the go_to_position() method with
        that coordinate as the parameter.

    III. PROTOCOL METHODS SECTION
        This section specifies methods needed to execute a scripted set of instructions recorded on an external file.

    IV. Labware
        This section defines a variety of methods that have to do with the creation, calibration, deletion, diretories, and models available for labware. 
        It also contains a method that allows for selecting a syringe model.

    V. Settings
        This section contains two main methods: get_current_settings() and update_setting(). The first returns a dictionary with all the relevant 
        settings of the system and the second updates a specific setting provided a setting name and the new value for it.There is also the 
        get_linked_joystick_axis_index() method which is a supporting function for the operation of both methods described above. It serves the purpose 
        of returning the joystick axis number linked to each coordinate axis in the motor system.

    VI. Feedback
        This section provides current values for dynamic variables and states such as the current X,Y,Z coordinate of the motors, and current gear, and 
        also adjusts values for variables that regulate the feedback sent to the user (like how fast the coordinates are refreshed on the web page).

"""

from drivers.OTdriver import OT2_nanotrons_driver, SYRINGE_SLOW_SPEED
from drivers.TDdriver import TempDeck
from drivers.TCdriver import Thermocycler
from protocol_creator import ProtocolCreator
import joystick
from joystick_profile import *
from labware_class import *
from models_manager import ModelsManager
from calibration import *
from deck import *
from keyboard import Keyboard
import asyncio
import threading
import math	
import time
import logging
import os
import sys
import platform
from constants import THERMOCYCLER_CONNECTED, TEMPDECK_CONNECTED
import json 

DISTANCE = 10 #mm
LINUX_OS = 'posix'
WINDOWS_OS = "nt"
MACBOOK_OS = 'Darwin'
UNIT_CONVERSION  = 4 #3.8896 4.16
INBETWEEN_LIFT_DISTANCE = -10 # Default distance the syringe will be lifted/lowered when going from one nanopots well\reagent pot to another
LABWARE_CHIP = "c"
LABWARE_PLATE = "p"
LABWARE_SYRINGE = "s"
DEFAULT_PROFILE = "default_profile.json"
PIPPETE_POSITION_WHEN_MOVING_TC_LID = '5'
FROM_NANOLITERS = 0.001
REFRESH_COORDINATE_INTERVAL = 0.1
POSITION_IN_Z_TO_PLACE_WHEN_GOING_TO_SLOT = 150
TIME_TO_SETTLE = 1 #SECOND
PLATE_DEPTH = "Plate's depth"
AIR_GAP_NL_AMOUNT = 50
AIR_GAP_ASPIRATING_Z_STEP_DISTANCE = 25

DEFAULT_RATE = 50 # nL/sec


STANDARD_LEFT_OVER = 200
STANDARD_CUSHION_1 = 200
STANDARD_CUSHION_2 = 300
AMOUNT_WANTED_DEFAULT = 1000


from constants import RUNNING_APP_FOR_REAL, CONTROLLER_CONNECTED


def interrupt_callback(res):
    sys.stderr.write(res)


class Coordinator:
    def __init__(self):
        """ Initialize the class and instanciate all the subordinate classes

        Args:method_name
            joystick_profile ([json file name]): specify a file with the mapping between joystick elements and methods triggered when those elements are pressed by user
        """
        operating_system = ""
        os_recognized = os.name
        # print(f"OS recognized in init: {os_recognized}")
        self.ot_control = OT2_nanotrons_driver()
        self.controller = joystick.XboxJoystick(operating_system)
        self.controller_profile = "profiles/default_profile.json"
        with open(self.controller_profile, 'r') as myfile:
            data = myfile.read()
        settingsObj = json.loads(data)
        self.controller_profile = settingsObj
        self.myLabware = Labware_class()
        self.allow_homing = False
        self.syringe_homing_warned = False
        self.tc_control = Thermocycler(interrupt_callback=interrupt_callback)
        self.td_control = TempDeck()
        self.protocol_creator = ProtocolCreator()
        self.calibration_points = [[0,0,0],[0,0,0],[0,0,0]]
        self.front_left_updated = False
        self.back_left_updated = False
        self.back_right_updated = False
        if os_recognized == WINDOWS_OS:
            logging.info("Operating system: Windows")
            # print("Init function Windows")
            operating_system = "w"
            if RUNNING_APP_FOR_REAL and CONTROLLER_CONNECTED:
                self.controller = joystick.XboxJoystick(operating_system)
            else:
                self.controller = Keyboard(self.ot_control)

        # really not sure if setup was ever completed/tested for other OS
        elif os_recognized == LINUX_OS: 
            logging.info("Operating system: Linux")
            operating_system = "r"
            if RUNNING_APP_FOR_REAL:
                if platform.system() == MACBOOK_OS:
                    self.myController = Keyboard(self.ot_control)
                else:
                    self.myController = XboxJoystick(operating_system)
        else:
            print("Operating system: ", os_recognized)

        
        self.myModelsManager = ModelsManager(operating_system)
        self.coordinates_refresh_rate = REFRESH_COORDINATE_INTERVAL
        self.deck = Deck()
        self.user_input = 0
        self.folder_for_pictures = 'default_folder'
        self.picture_flag = False
        self.toggle_flag = False

        # variables for protocols.
        self.clean_water = None
        self.wash_water = None
        self.waste_water = None
        self.amount_wanted = AMOUNT_WANTED_DEFAULT

        # initialize the logging info format
        format = "%(asctime)s: %(message)s" #format logging
        logging.basicConfig(format=format, level=logging.INFO,
                            datefmt="%H:%M:%S")
                  

    def set_picture_flag(self, value: bool):
        print(f"Setting picture flag to: {value}")
        self.picture_flag = value

    def get_picture_flag(self) -> bool:
        return self.picture_flag

    def set_toggle_flag(self, value: bool):
        print(f"Setting toggle flag to: {value}")
        self.toggle_flag = value

    def get_toggle_flag(self) -> bool:
        return self.toggle_flag

    def set_folder_for_pictures(self, folder: str):
        print(f"COOR: Folder set to: {folder}")
        self.folder_for_pictures = folder

    def get_folder_for_pictures(self) -> str:
        print(f"Getting the folder for pictures: {self.folder_for_pictures}")
        return self.folder_for_pictures
        
    """
    MANUAL CONTROL SECTION
        The only method that should be called on an instance of the Application class is manual_control(). The
        rest of the methods are supporting functions for the operation of manual_control()
    """
    def get_syringe_settings(self):
        settingsDic = {}
        settingsDic["s step"] = self.ot_control.get_step_size_syringe_motor()
        settingsDic["nL"] = self.ot_control.get_nL()
        settingsDic["xyz step"] = self.ot_control.get_step_size_xyz_motor()
        settingsDic['pipette'] = self.ot_control.get_side()
        settingsDic['x'] = self.ot_control.position['X']
        settingsDic['y'] = self.ot_control.position['Y']
        settingsDic['z'] = self.ot_control.position['Z']
        settingsDic['b'] = self.ot_control.position['B']
        settingsDic['c'] = self.ot_control.position['C']
        return settingsDic

    def start_listening(self):
        self.controller.start_pygame()
        self.controller.listen()

    def stop_joystick_control(self):
        """ This method turns off the flag that enables listening to the joystick, which triggers killing manual control given that the loop depends on that flag
        """
        try:
            self.controller.stop_joystick = True
        except AttributeError:
            print("Trying to stop listening controller inputs but no controller connected")
    
    def joystick_control(self):
        """ This method opens a secondary thread to listen to the input of the joystick (have a real time update of the triggered inputs) and calls monitor_joystick on the main thread on a loop
        """
        self.controller.stop_joystick = False

        if not self.controller.pygame_running:
            t1 = threading.Thread(target=self.start_listening)
            t1.start()
            while(t1.is_alive()):
                self.monitor_joystick()
                time.sleep(0.1)
            self.stop_joystick_control()
        else:
            pass

    
    def monitor_joystick(self):
        """ This method reads the values being collected from triggered inputs in the joystick and executes the methods associated with them
        """
        buttons, hats, axes,  = self.controller.deliver_joy()
        self.controller.reset_values()
        syringe_model = self.myLabware.get_syringe_model()
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)

        for button in buttons:
            method_name = self.controller_profile[button]
            method = getattr(self.ot_control, method_name, False)
            method(self.ot_control.xyz_step_size)


        for axis in axes:
            method_name = self.controller_profile[axis]
            method = getattr(self.ot_control, method_name, False)
            method(self.ot_control.xyz_step_size)

        
        # if len(button) != 0:
        #     if button[0] == "START":
        #         if self.myLabware.syringe_model_is_default:
        #             print("Please select a syringe model (start) ")
                
        #         else :
        #             # print(f"Current syringe model is: {syringe_model}")
        #             self.user_input = input("Enter volume in nanoliters: ")
        #             self.ot_control.set_nL(self.user_input)
        #             self.user_input2 = input("Enter flow-rate in nanoliters per second: ")
        #             #self.ot_control.set_nL(self.user_input2) (Not being used currently)
        #             self.ot_control.set_step_speed_syringe_motor(self.flowrate_to_speed_converter(float(self.user_input2)))
        #             self.ot_control.set_step_size_syringe_motor(self.volume_to_distance_converter(int(self.user_input)))
        #             print('')
            
        #     elif button[0] == "A":
        #         if (self.ot_control.side == LEFT):
        #             self.ot_control.Z_axis_Down(self.ot_control.xyz_step_size)
        #         else:
        #             self.ot_control.A_axis_Down(self.ot_control.xyz_step_size)
        #     elif button[0] == "B":
        #         self.ot_control.report_current_position()
        #     elif button[0] == "X":
        #         self.ot_control.change_vertical_axis()
        #     elif button[0] == "Y":
        #         if self.ot_control.side == LEFT:
        #             self.ot_control.Z_axis_Up(self.ot_control.xyz_step_size)
        #         else: 
        #             self.ot_control.A_axis_Up(self.ot_control.xyz_step_size)
        #     elif button[0] == "RB":
        #         self.ot_control.step_size_up()
        #     elif button[0] == "LB":
        #         self.ot_control.step_size_down()
        #     elif button[0] == "LSTICK":
        #         pass
        #     elif button[0] == "RSTICK":
        #         print("Right stick button pressed")
        #         self.ot_control.update_pipette_attachment_status() # Toggles pipette attachment, default is attached
        #         print("Pipette status updated")
        #     elif button[0] == "BACK":
        #         self.controller.stop_joystick = True

        # if len(hat) != 0:
        #     if hat[0] == "HAT_UP":
        #         self.allow_homing = True
        #         print("\nController homing enabled.\n")

        #     elif hat[0] == "HAT_LEFT":
        #         if self.allow_homing == True:
        #             if self.syringe_homing_warned:
        #                 print("Homing left syringe\n")
        #                 self.ot_control.home('B')
        #                 self.allow_homing = False
        #             else:
        #                 print("\n****************************************************************************")
        #                 print("Syringe homing will fail if initial position is too far from limit switch.")
        #                 print("Dont Know Why...")
        #                 print("Move syringe position within range (approx 25 mm)\nbefore initiating manual homing of syringe.")
        #                 print("Press button again to proceed with syringe homing (if you dare...)!")
        #                 print("****************************************************************************\n")
        #                 self.syringe_homing_warned = True
        #         else:
        #             print("Homing not enabled")

        #     elif hat[0] == "HAT_RIGHT":
        #         if self.allow_homing == True:
        #             if self.syringe_homing_warned:
        #                 print("Homing right syringe")
        #                 self.ot_control.home('C')
        #                 self.allow_homing = False
        #             else:
        #                 print("\n****************************************************************************")
        #                 print("Syringe homing will fail if initial position is too far from limit switch.")
        #                 print("Dont Know Why...")
        #                 print("Move syringe position within range (approx 25 mm)\nbefore initiating manual homing of syringe.")
        #                 print("Press button again to proceed with syringe homing (if you dare...)!")
        #                 print("****************************************************************************\n")
        #                 self.syringe_homing_warned = True
        #         else:
        #             print("Homing not enabled")

        #     elif hat[0] == "HAT_DOWN":
        #         if self.allow_homing == True:
        #             self.ot_control.home('XYZA')
        #             self.allow_homing = False
        #         else:
        #             print("Homing not enabled")
                

        # if len(axis) != 0:
        #     if axis[0] == "L_STICK_LEFT":
        #         # print("left")
        #         self.ot_control.move_left(self.ot_control.xyz_step_size)
        #     elif axis[0] == "L_STICK_RIGHT":
        #         # print("right")
        #         self.ot_control.move_right(self.ot_control.xyz_step_size)
        #     elif axis[0] == "L_STICK_UP":
        #         # print("back")
        #         self.ot_control.move_forward(self.ot_control.xyz_step_size)
        #     elif axis[0] == "L_STICK_DOWN":
        #         # print("front")
        #         self.ot_control.move_back(self.ot_control.xyz_step_size)

        #     elif axis[0] == "R_STICK_LEFT":
        #         pass
        #     elif axis[0] == "R_STICK_RIGHT":
        #         pass
        #     elif axis[0] == "R_STICK_UP":
        #         if(self.ot_control.side == LEFT):
        #             self.ot_control.plunger_L_Up(self.ot_control.syringe_step_size, self.ot_control.syringe_step_speed, syringe_model, syringe_parameters)
        #             print('')
        #         else:
        #             self.ot_control.plunger_R_Up(self.ot_control.syringe_step_size, self.ot_control.syringe_step_speed, syringe_model, syringe_parameters)
        #     elif axis[0] == "R_STICK_DOWN":
        #         if(self.ot_control.side == LEFT):
        #             self.ot_control.plunger_L_Down(self.ot_control.syringe_step_size, self.ot_control.syringe_step_speed, syringe_model, syringe_parameters)
        #         else:
        #             self.ot_control.plunger_R_Down(self.ot_control.syringe_step_size, self.ot_control.syringe_step_speed, syringe_model, syringe_parameters)
        #     elif axis[0] == "L_TRIGGER":
        #         pass
        #     elif axis[0] == "R_TRIGGER":
        #         pass

    
    def home_all_motors(self):
        """ This method homes all the motors on the OT2 except for the Syringes
        """
        print("self.ot_control.home('X Y Z A')")
        self.ot_control.home("X Y Z A") # Not B and C

    def up_step_size(self):
        """ This method goes through a list of predefined steps 
        """
        self.ot_control.double_step_size_XYZ("") # "" is the dummy argument
    
    def down_step_size(self):
        """ This method goes through a list of predefined steps  """
       
        self.ot_control.half_step_size_XYZ("") # "" is the dummy argument



    """
    INSTANTANEOUS COMMANDS SECTION
        This section contains code that can send instantaneous commands to the motors to go to
        a specific well or pot in a given chip or plate, respectively. It also implements methods that
        allow for either picking up or dropping off spcific amounts of volumes of liquid 
    """
    def go_to_position(self, location):
        """ 
        This method moves the motor system to a target 3D location on a sequence of safety displacements as follows:
            1. Lift Z axis
            2. Move to the X and Y target positions
            3. Descend to the Z target position

        Args:
            location ([tuple]): contains three float numbers indicating a target 3D coordinate
        """
        self.ot_control.move_to(location=location)

    def go_to_position_to_take_picture(self, location):
        """ 
        This method moves the motor system to a target 3D location on a sequence of safety displacements as follows:
            1. Lift Z axis
            2. Move to the X and Y target positions
            3. Descend to the Z target position

        Args:
            location ([tuple]): contains three float numbers indicating a target 3D coordinate
        """
        if THERMOCYCLER_CONNECTED:
            self.open_lid() # Prevents the pipette to crash with the thermocycler
        x = location[0]
        y = location[1]
        z = location[2] + 3
        picture_location = [x, y, z]
        self.ot_control.move_to(location=picture_location)
        
    def go_to_deck_slot(self, slot):
        """ This method goes allows the OT2 to move to a designated physical slot  """
        slot_number = float(slot)
        logging.info(f"Moving to slot {slot}")
        x = self.deck.get_slot_center(slot)[0]
        y = self.deck.get_slot_center(slot)[1]
        z = POSITION_IN_Z_TO_PLACE_WHEN_GOING_TO_SLOT
        location = [x, y, z]
        if (slot_number == 7 or slot_number == 8 or slot_number == 10 or slot_number == 11):
            self.open_lid() # We open the lid first to avoid collitions
            if self.ot_control.tc_lid_flag == 'open': 
                self.go_to_position(location)
        else:   
            self.go_to_position(location)        

    def go_to_well(self, model, well_nickname):
        """ This method moves the system to the location assigned to a specific pot in a plate by retrieving the location from myLabware and then calling go_to_position()

        Args:
            plate ([int]): this is the index of the Plate object contained in Labware
            pot_nickname ([str]): this is a string representing the nickname of the well i.e. 'C4' or 'D9'
        """
        # Get the location of the well by its nickname
        location = self.myLabware.get_well_location(model, well_nickname) # [x, y, z]
        self.go_to_position(location)
    
    def pick_up_liquid(self, volume, rate = DEFAULT_RATE): 
        """ Sends a command to the syringe motor to displace a distance that is equivalent to aspirating a given volume of liquid

        Args:
            volume ([float]): volume of liquid to be aspirated. UNIT: NANOLITERS
            speed ([float]): speed at which the given volume of liquid will be aspirated. UNIT: MILIMITERS/SECOND
        """ 

        speed = self.flowrate_to_speed_converter(rate)
        step_displacement = self.volume_to_distance_converter(volume) 
        syringe_model = self.myLabware.get_syringe_model()
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        self.ot_control.plunger_L_Up(step_displacement, speed, syringe_model, syringe_parameters)

    def drop_off_liquid(self, volume, rate = DEFAULT_RATE):
        """ Sends a command to the syringe motor to displace a distance that is equivalent to dispensing a given volume of liquid

        Args:
            volume ([float]): volume of liquid to be dispensed,. UNIT: NANOLITERS
            speed ([float]): speed at which the given volume of liquid will be dispensed. UNIT: MILIMITERS/SECOND
        """
        speed = self.flowrate_to_speed_converter(rate)
        step_displacement = self.volume_to_distance_converter(volume)
        syringe_model = self.myLabware.get_syringe_model()
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        self.ot_control.plunger_L_Down(step_displacement, speed, syringe_model, syringe_parameters)
    
    def volume_to_distance_converter(self, volume):
        """ This method converts a certain amount of volume into displacement needed to move that amount 
            of liquid in the syringe by retrieving the syringe dimensions from the system and doing some simple math

        Args:
            volume ([float]): volume of liquid to be converted. UNIT: NANOLITERS

        Returns:
            [float]: motor distance that results in the displacement of the provided volume on the syringe. UNIT: MILLIMETERS
        """
        # Get the current syringe model
        syringe_model = self.myLabware.get_syringe_model()
        
        # Extract syringe radius
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        diameter = syringe_parameters["inner_diameter"] # This parameter has units of mm
        radius = diameter / 2

        # Calculate area and distance (height of the cylindric volume)
        area = (math.pi * radius * radius) # Basic formula for area
        distance_in_mm = volume * FROM_NANOLITERS / area # Volume is assumed to come in nanoLiters to it's converted to microliters to perform accurate calculations
        distance_to_feed_to_stepper_motor = distance_in_mm * UNIT_CONVERSION # something is off with the syringe motors, so distances have to be adjusted

        # print(f"Distance: {distance_in_mm} mm")
        # Return the distance needed to displace that amount of volume
        return distance_to_feed_to_stepper_motor

    def flowrate_to_speed_converter(self, rate):
        """ This method converts a flowrate (nL/s) into speed (mm/s) appropriate for the current syringe 
            It does this by retrieving the syringe dimensions from the system and doing some simple math

        Args:
            rate ([float]): flowrate of liquid transfer to be converted to speed. UNIT: NANOLITERS/S

        Returns:
            [float]: speed to be used by the syringe motor. UNIT: MILLIMETERS
        """
        # Get the current syringe model
        syringe_model = self.myLabware.get_syringe_model()
        
        # Extract syringe radius
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        diameter = syringe_parameters["inner_diameter"] # This parameter has units of mm
        radius = diameter / 2
                 
        # rate = nL/sec
        # print(f"Rate: {rate} nL/s")
        # Calculate area and distance (height of the cylindric volume)
        area = (math.pi * radius * radius) # Basic formula for area
        speed_in_mm_s = rate * FROM_NANOLITERS / area * UNIT_CONVERSION # rate is assumed to come in nanoLiters/s, it's converted to microliters/s, then to mm/s 
        # print(f"speed: {speed_in_mm_s / UNIT_CONVERSION} mm/s")

        # print(f"Speed: {speed_in_mm_s} mm/s")
        # Return the speed to be used 
        return speed_in_mm_s
        
    def aspirate(self, volume, rate = DEFAULT_RATE):
        """ Pick up amount in nL and speed in nL/s  """
        logging.info(f"Aspirating {volume} nL at speed {rate} nL/s")
        self.pick_up_liquid(int(volume), rate) # Pick up the amount needed

    def dispense(self, volume, rate = DEFAULT_RATE): 
        """ Drop of amount in nL and speed in nL/s  """
        logging.info(f"Dispensing {volume} nL at speed {rate} nL/s")
        self.drop_off_liquid(int(volume), rate)

    def air_gap(self):
        """This is the function that allows the user to have an 50 nL airgap in the syringe"""
        x = self.ot_control._position['X']
        y = self.ot_control._position['Y']
        z = self.ot_control._position['Z'] + AIR_GAP_ASPIRATING_Z_STEP_DISTANCE
        new_location = [x, y, z]
        self.go_to_position(new_location)
        self.aspirate(AIR_GAP_NL_AMOUNT, rate = DEFAULT_RATE)

    """
    LABWARE METHODS SECTION
        This section specifies methods related to the adding and removing of labware components
    """
    def get_component_models_location(self, component_type):
        """ Obtains the path in the system files to the location of chip, plate, or syringe model files

        Args:
            component_type ([str]): either 'c', 'p', or 's' for chip, plate, or syringe, respectively

        Returns:
            [str]: string describing the path to the location of the files of the specified component type
        """
        return self.myModelsManager.get_path(component_type)

    def get_available_component_models(self):
        """ Retrieve the available models registered in the system for chips, plates, and syringes

        Returns:
            [dict]: dictionary with three keys ("chips", "plates", and "syringes") that map to strings that correspond to the names of each of the models
        """
        return self.myModelsManager.get_stored_models()

    def create_new_chip_model(self, properties):
        """This method creates a new chip model (in a json file) using the provided dictionary of parameters and calling the corresponding
        method in ModelsManager which actually imports things to a file and saves it on the right directory

        Args:
            properties ([dict]): defines all the parameters for a new chip model (according to the properties defined in a regular chip file)
        """
        new_model_name = properties["chip_new_model_name"]
        grid = [int(properties["chip_grid_rows"]), int(properties["chip_grid_columns"])]
        offset = float(properties["chip_offset"])
        well_depth = float(properties["chip_well_depth"])
        nicknames = properties["nicknames"]
        self.myModelsManager.create_chip_model(new_model_name, grid, offset, well_depth, nicknames)
    
    def create_new_plate_model(self, properties):
        """This method creates a new plate model (in a json file) using the provided dictionary of parameters and calling the corresponding
        method in ModelsManager which actually imports things to a file and saves it on the right directory

        Args:
            properties ([dict]): defines all the parameters for a new plate model (according to the properties defined in a regular plate file)
        """
        new_model_name = properties["plate_new_model_name"]
        grid = [int(properties["plate_grid_rows"]), int(properties["plate_grid_columns"])]
        offset = float(properties["plate_offset"])
        well_depth = float(properties["plate_well_depth"])
        nicknames = properties["nicknames"]
        self.myModelsManager.create_plate_model(new_model_name, grid, offset, well_depth, nicknames)
    
    def create_new_syringe_model(self, properties):
        """This method creates a new syringe model (in a json file) using the provided dictionary of parameters and calling the corresponding
        method in ModelsManager which actually imports things to a file and saves it on the right directory

        Args:
            properties ([dict]): defines all the parameters for a new syringe model (according to the properties defined in a regular syringe file)
        """
        new_model_name = properties["syringe_new_model_name"]
        volume = float(properties["syringe_volume"])
        inner_diameter = float(properties["syringe_inner_diameter"])
        upper_limit = float(properties["syringe_upper_limit"])
        lower_limit = float(properties["syringe_lower_limit"])
        sweetspot = float(properties["syringe_sweetspot"])
        self.myModelsManager.create_syringe_model(new_model_name, volume, inner_diameter, upper_limit, lower_limit, sweetspot)

    def get_current_labware(self):
        """ Obtains a disctionary with the components currently calibrated and loaded onto the system and ready to be used

        Returns:
            [dict]: dictionary with three keys ("chips", "plates", and "syringe") that map to lists of Chip and Plate onbjects and string with the name of the syringe being used
        """
        return self.myLabware.get_current_labware()

    def get_full_current_labware(self):
        """ This method returns a dictionary with all the labware components and their properties. For description on detailed contents, visit the documentation on labware_to_dictionary() in the Labware class

        Returns:
            [dict]: dictionary with all the labware components and all their properties
        """
        return self.myLabware.labware_to_dictionary()

    def save_labware_setup(self, output_file_name):
        """ Exports all the calibrated components to a file that can later be loaded onto the system to avoid recalibrating each component individually

        Args:
            output_file_name ([str]): desired name of output file
        """
        self.myLabware.save_labware_to_file(output_file_name)
    
    def load_labware_setup(self, input_file_name):
        """ Import previously calibrated and saved labware components from a json file to avoid recalibrating them individually

        Args:
            input_file_name ([str]): name of desired input file
        """
        
        print(f"\nLoading labware from {input_file_name}\n")
        self.myLabware.load_labware_from_file(input_file_name)
        labware = self.myLabware.model_list
        return labware

    def load_syringe_setup(self, loaded_syringe):
        """ Import previously calibrated and saved labware components from a json file to avoid recalibrating them individually

        Args:
            input_file_name ([str]): name of desired input file
        """
        print(f"Coordinator: Loading labware from {loaded_syringe}")
        
        return self.myLabware.set_syringe_model(loaded_syringe)

    def get_available_labware_setup_files(self):
        """ Obtain the list of available files with previously calibrated and exported labware components

        Returns:
            [list]: list of strings of names of files with previously calibrated labware components 
        """
        return self.myLabware.available_saved_labware_files()

    def get_available_syringe_files(self):

        return self.myLabware.available_saved_syringe_files()

    def guess_fourth_calibration_point(self, calibration_points):
        """ Guess the fourth point that defines a rectangle (plane) in 3D

        Args:
            calibration_points ([list]): list of three lists, each of which represents a point in 3 dimensions

        Returns:
            [list]: list containing 3 float numbers representing a 3D point in space that completes a rectangle with the three points provided in the argument of the function
        """

        return guess_fourth_calibration_point(calibration_points)
        
    def add_labware_component(self, labware_component, component_model, calibration_points):
        """ Add a labware component to the list of calibrated components in the system

        Args:
            labware_component ([str]): describes whether the component is a chip ('c') or a plate ('p')
            component_model ([str]): model name of the component being added
            calibration_points ([list]): list with the calibration points of the component
        """
        # This method finds the file named component_model and returns the content of that file as a dictionary
        component_parameters = self.myModelsManager.get_model_parameters(labware_component, component_model)

        if (labware_component == LABWARE_CHIP):
            mapped_well_locations = calibrate_model(component_parameters, calibration_points) # Map out components within the chip
            new_component = create_component(component_model, component_parameters, mapped_well_locations) # Create Chip object with all the internal information it needs
            self.myLabware.add_model(new_component) # Add chip to Chamber

        elif (labware_component == LABWARE_PLATE):
            mapped_pot_locations = calibrate_model(component_parameters, calibration_points) # Map out components within the plate
            new_component = create_component(component_model, component_parameters, mapped_pot_locations) # Create Plate object with all the internal information it needs
            self.myLabware.add_model(new_component) # Add plate to Chamber

    def remove_labware_component(self, labware_component, component_index):
        """ Delete a calibrated labware component from the list of current labware components

        Args:
            labware_component ([str]): describes whether the component is a chip ('c') or a plate ('p')
            component_index ([int]): index of the component in the list of chips or plates
        """
        if (labware_component == LABWARE_CHIP):
            self.myLabware.remove_model(component_index)
            
        elif (labware_component == LABWARE_PLATE):
            self.myLabware.remove_model(component_index)

    def set_syringe_model(self, syringe_model):
        """ Set the model of the syringe currenly being operated

        Args:
            syringe_model ([str]): name of the model of syringe
        """
        self.myLabware.set_syringe_model(syringe_model)

    """
    SETTINGS SECTION
    """
    
    def get_current_settings(self):
        """ Retrieve the current state of all the relevant settings of the system and store them in a dictionary

        Returns:
            [dict]: contains a mapping of setting keywords and values for all the relevant settings of the system
        """
        settings_dict = dict()

        settings_dict["coordinate_refresh_rate"] = self.coordinates_refresh_rate

        settings_dict["syringe_model"] = self.get_current_labware()["syringe"]
        settings_dict["syringe_default_speed"] = self.ot_control.get_step_speed_syringe_motor()
        
        settings_dict["xyz_axis_step_size"] = self.ot_control.get_step_size_xyz_motor()
        settings_dict["xyz_axis_step_speed"] = self.ot_control.get_step_speed_xyz_motor()
        return settings_dict

    def update_setting(self, property_name, value):
        """ Update the value of a given setting in the system

        Args:
            property_name ([str]): keyword that matches the value of any of the if statements within this method
            value ([various]): value to be loaded on the setting being updated
        """
        # Go through all the cases and adjust the appropriate property

        if property_name == "coordinate_refresh_rate":
            self.coordinates_refresh_rate = float(value)

        elif property_name == "syringe_model":
            self.set_syringe_model(value)
        elif property_name == "syringe_default_speed":
            self.ot_control.set_step_speed_syringe_motor(float(value))

        elif property_name == "xyz_axis_step_size":
            self.ot_control.set_step_size_xyz_motor(float(value))
        elif property_name == "xyz_axis_step_speed":
            self.ot_control.set_step_speed_xyz_motor(float(value))
        elif property_name == "xyz_axis_gearbox":
            self.ot_control.set_x_motor_gearbox([float(i) for i in value.split(",")])
     

        # ADD MORE SETTING HANDLERS BELOW. FORMAT:
        # elif property_name == "xxxxxxxxxxx":
        #     pass
        
        else:
            logging.info(f"ERROR: {property_name} PROPERTY NOT LINKED TO ANY MODIFICATION ON THE SYSTEM\n") 

    """
    FEEDBACK SECTION
        This section is meant to define methods that retrieve information from the 
        components of the system
    """
    
    def get_current_coordinates(self):
        """ Gets the position of each of the stages associated with 3 dimensional motion: X, Y, and Z axes

        Returns:
            [float]: three float numbers rounded to the third decimal point representing X, Y, and Z coordinates
        """
        return (self.ot_control._position['X'], self.ot_control._position['Y'], self.ot_control._position['Z'])

    def get_coordinate_refresh_rate(self):
        """ Get the period for refreshing the coordinates in the GUI

        Returns:
            [float]: time elapsed between every instance when the coordinates are refreshed in the GUI
        """
        return self.coordinates_refresh_rate

    def set_coordinate_refresh_rate(self, new_rate):
        """ Set the period for refreshing the coordinates in the GUI

        Args:
            new_rate ([float]): time elapsed between every instance when the coordinates are refreshed in the GUI
        """
        self.coordinates_refresh_rate = new_rate

    def get_type_of_labware_by_slot(self, slot: int, model: Model = None):
        if model != None:
            model_well_properties = model.export_model_properties()

        return model_well_properties

    def get_depth_of_labware(self, labware: Model):
        model_well_properties = labware.export_model_properties()
        depth = model_well_properties["well_depths"]
        return depth

    def set_plate_depth(self, model, depth):
        # .get_depth_of_labware return a list, so we get the first elements since all of the deoths are the same [0]
        plate_default_depth = self.get_depth_of_labware(model)[0]
        if depth == PLATE_DEPTH:
            # we set the depth here to the distance of the pot minus 1 milimiter so that it has some room. 
            return plate_default_depth - 1
        # if the depth value is an integer it means that the user wants to dispense or aspirate at a higher point that is smaller in distance than the plates depth, otherwise it would hit the bottom of the plate 
        elif (type(depth) == int) and (depth < plate_default_depth): 
            if depth < plate_default_depth:
                return depth
            else: 
                print("Number input for depth greater than allowed, using default depth. ")
                return None 
        else: 
            return None


    '''
    PROTOCOL METHODS SECTION FOR OT2
        This section defines methods that get called to facilitate reading a script of instructions 
    '''
    def aspirate_from(self, volume, position, rate = DEFAULT_RATE):
        """ This will go to the position of the source and aspirate an amount in nL"""
        self.go_to_position(position)
        self.pick_up_liquid(int(100), rate) # Pick up an extra 100 for backlash, doesn't log action
        self.aspirate(volume, rate) # Pick up target volume
        self.drop_off_liquid(int(100), rate) # Drop off liquid to account for backlash, doesn't log action
        time.sleep(TIME_TO_SETTLE) # Allow some time to the syringe to aspirate

    def dispense_to(self, volume, position, rate = DEFAULT_RATE):
        """ This will go to the position of the destination and dispense an amount in nL"""
        self.go_to_position(position)
        self.dispense(volume, rate)
        time.sleep(TIME_TO_SETTLE) # Allow some time to the syringe to dispense
        
    def move_plunger(self, position, speed = SYRINGE_SLOW_SPEED):
        """ This allows the protocol to move the plunger passed the set limit for manual control, 
            it is important to understand that if the right values are not input correctly for 
            the syringe being used, this could break """
        self.ot_control.move({'B': position}, speed = speed)

    def set_washing_positions(self, clean_water, wash_water, waste_water):
        """ For every protocol we assume the scientist will have these three location in which the 
            different types of water are places for washing the syringe so that there is no contamination"""
        self.clean_water = clean_water
        self.wash_water = wash_water
        self.waste_water = waste_water
    
    def set_amount_wanted(self, volume):
        # print(f"Amount wanted to clean for midwash: {volume}")
        self.amount_wanted = volume

    def start_wash(self, rate):
        """ This is the function that allows the robot to get rid of the contamination on the syringe, 
            by dispensing everything that was left over from before, then it will pick up clean water 
            and end in a postition that allows the protocol to aspirate and dispense without hitting limmmits"""
        # Go to waste and SYRINGE_BOTTOM
        syringe_model = self.myLabware.get_syringe_model()
        # print (f" start wash syringe: {syringe_model}")
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        syringe_bottom_coordinate = syringe_parameters["lower_syringe_limit"] # This parameter is a coordinate on the B axis
        syringe_top_coordinate = syringe_parameters["upper_syringe_limit"] # This parameter is a coordinate on the B axis
        syringe_sweet_spot_coordinate = syringe_parameters["sweetspot_on_syringe"] # This parameter is a coordinate on the B axis

        speed = self.flowrate_to_speed_converter(rate)

        # print(f"Syringe position is {self.ot_control._position['B']}")
        self.go_to_position(self.waste_water)
        # print (f"syringe_bottom_coordinate: {syringe_bottom_coordinate}")
        self.move_plunger(syringe_bottom_coordinate, speed)
        # Go to wash, SYRINGE_TOP, SYRINGE_BOTTOM
        self.go_to_position(self.wash_water)
        self.move_plunger(syringe_top_coordinate, speed)
        self.move_plunger(syringe_bottom_coordinate, speed)
        # Go to clean, SYRINGE_SWEET_SPOT
        self.go_to_position(self.clean_water)
        self.move_plunger(syringe_sweet_spot_coordinate, speed)
        # Airgap
        self.air_gap()

    def mid_wash(self, left_over, cushion_1, cushion_2, rate):
        """ This is a wash that is done to the syringe when picking up and dispensing different liquids"""
        # Go to waste, dispense left overs
        syringe_model = self.myLabware.get_syringe_model()
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        syringe_sweet_spot_coordinate = syringe_parameters["sweetspot_on_syringe"] # This parameter is a coordinate on the B axis
        speed = self.flowrate_to_speed_converter(rate)
        
        self.go_to_position(self.waste_water)
        self.dispense(left_over,rate)
        # Go to wash, aspirate amount wanted + Cushion 1, dipense amount wanted + Cushion 2
        self.go_to_position(self.wash_water)
        self.aspirate(self.amount_wanted + cushion_1, rate)
        self.dispense(self.amount_wanted + cushion_2, rate)
        # Go to clean, go to sweet spot
        self.go_to_position(self.clean_water)
        self.move_plunger(syringe_sweet_spot_coordinate, speed)
        # Airgap
        self.air_gap()

    def fill_syringe_with_water(self, rate):
        """ This is the function that allows the robot to fill the syringe with water at the end of a day 
            or protocol so that if it evaporates there is still some more the next day"""
        # Go to clean, SYRINGE_TOP
        syringe_model = self.myLabware.get_syringe_model()
        syringe_parameters = self.myModelsManager.get_model_parameters(LABWARE_SYRINGE, syringe_model)
        upper_syringe_limit = syringe_parameters["upper_syringe_limit"]
        speed = self.flowrate_to_speed_converter(rate)
        self.go_to_position(self.clean_water)
        self.move_plunger(upper_syringe_limit, speed)


    """
    PROTOCOL METHODS SECTION FOR THERMOCYCLER 
    """
    

    def open_lid(self):
        """ This function opens the lid once the pipette is out of the way and sitting on the slot 3 of the deck,
            then it sets a flag so that other functions may know that the thermocycler lid is opened"""
        if self.ot_control.tc_lid_flag != 'open':
            self.go_to_deck_slot(PIPPETE_POSITION_WHEN_MOVING_TC_LID) # for avoiding collitions
        asyncio.run(self.tc_control.open())
        self.ot_control.set_tc_lid_flag('open')

    def close_lid(self):
        """ This function closes the lid once the pipette is out of the way and sitting on the slot 3 of the deck,
            then it sets a flag so that other functions may know that the thermocycler lid is closed"""
        self.go_to_deck_slot(PIPPETE_POSITION_WHEN_MOVING_TC_LID) # for avoiding collitions
        asyncio.run(self.tc_control.close())
        self.ot_control.set_tc_lid_flag('closed')

    def open_close_lid(self):
        """ This function closes the lid once the pipette is out of the way and sitting on the slot 3 of the deck,
            then it sets a flag so that other functions may know that the thermocycler lid is closed"""

        self.go_to_deck_slot(PIPPETE_POSITION_WHEN_MOVING_TC_LID) # for avoiding collitions
        if self.ot_control.tc_lid_flag == 'open':
            asyncio.run(self.tc_control.close())
            self.ot_control.set_tc_lid_flag('closed')
        else:
            asyncio.run(self.tc_control.open())
            self.ot_control.set_tc_lid_flag('open')


    def deactivate_all(self):
        """ This function deactivates both, the lid and the block of the thermocycler"""
        asyncio.run(self.tc_control.deactivate_all())
    
    def deactivate_lid(self):
        """ This function deactivates the lid of the thermocycler"""
        asyncio.run(self.tc_control.deactivate_lid())

    def deactivate_block(self):
        """ This function deactivates the block of the thermocycler"""
        asyncio.run(self.tc_control.deactivate_block())

    def set_temperature(self ,temp: float, hold_time:  float = None):
        """ This function sets the temperature of the thermocycler with a holding time in minutes."""
        asyncio.run(self.tc_control.set_temperature(temp, hold_time))

    def set_lid_temp(self, temp: float):
        
        asyncio.run(self.tc_control.set_lid_temperature(temp))

    def tc_disconnect(self):
        self.tc_control.disconnect()

    def set_block_temp(self, target_temp, holding_time_in_minutes):
        hold_time_in_secs = holding_time_in_minutes * 60
        self.set_temperature(temp=target_temp, hold_time=hold_time_in_secs)
        current_temp = float(self.tc_control.get_block_temp())
        logging.info("Checking temperature of the block")
        logging.info(f"Current_temp = {current_temp} [C] ---- Target Temperature = {target_temp} [C]")
        
        # While the target temperature has not been reached within a 1 of allowance check every five seconds and then continue to hold for specified time
        while (float(current_temp) < (float(target_temp) - 1)) or (float(current_temp) > (float(target_temp) + 1)):
            current_temp = self.tc_control.get_block_temp()
            time.sleep(5)
            logging.info(f"Current_temp = {current_temp} [C]")
        logging.info("Target temperature {current_temp} [C] reached")

        logging.info(f"Holding for {holding_time_in_minutes} minutes.")
        min_count = 0 # init for tcounting the minutes to hold

        # here we start the holding time. We check every half a minute and exit the loop when the time holding is equal than the time to hold
        while float(min_count) < float(holding_time_in_minutes):
            time.sleep(30)
            min_count = min_count + 0.5
        logging.info("Holding time done. Proceeding to complete next step.")

    """
    PROTOCOL METHODS SECTION FOR TEMPDECK 
    """

    def set_tempdeck_temp(self, celcius, holding_time_in_minutes):
        hold_time_in_secs = holding_time_in_minutes * 60
        self.td_control.start_set_temperature(celcius)
        current_temp = self.get_tempdeck_temp()
        logging.info("Checking temperature of the TempDeck")
        logging.info(f"Current_temp = {current_temp} [C] ---- Target Temperature = {celcius} [C]")

        # While the target temperature has not been reached within a 1 of allowance check every five seconds and then continue to hold for specified time
        while (float(current_temp) < (float(celcius) - 1)) or (float(current_temp) > (float(celcius) + 1)):
            current_temp = self.get_tempdeck_temp()
            time.sleep(5)
            logging.info(f"Current_temp = {current_temp} [C]")
            # print(self.check_tempdeck_status())
        logging.info("Target temperature {current_temp} [C] reached")

        logging.info(f"Holding for {holding_time_in_minutes} minutes.")
        min_count = 0 # init for tcounting the minutes to hold

        # here we start the holding time. We check every half a minute and exit the loop when the time holding is equal than the time to hold
        while float(min_count) < float(holding_time_in_minutes):
            time.sleep(30)
            min_count = min_count + 0.5
        logging.info("Holding time done. Proceeding to complete next step.")

    def deactivate_tempdeck(self):
        self.td_control.deactivate()

    def get_tempdeck_temp(self):
        self.td_control.update_temperature()
        time.sleep(0.01)
        return self.td_control.temperature

    def check_tempdeck_status(self):
        return self.td_control.status

    """
    RUN PROTOCOL COORDINATION SECTION
    """

    def stop_protocol(self):
        """This method stops the protocol process"""
        pass

    def verify_container_existence(self, container_description):
        """Verify that a given well or pot exists in a given chip or plate, respectively, by providing a coded description
            String input looks like: "p 1E3" or "c 1B3" : "[component] [component_index][well/pot nickname]"

        Args:
            container_description ([str]): string that describes what container needs to be verified
        """
        return self.myLabware.check_well_existence(container_description)

    def connect_all(self):
        """This method connects the modules connected to the computer"""
        try:
            self.disconnect_all()
            if THERMOCYCLER_CONNECTED:
                self.tc_control._connection = self.tc_control._connect_to_port()
            self.ot_control.connect_driver()
            if TEMPDECK_CONNECTED:
                self.td_control.connect(self.ot_control._port)
        except TypeError:
            print("Not able to disconnect and connect back to the modules")

    def disconnect_all(self):
        """This method disconnects the modules connected to the computer"""
        self.tc_disconnect()
        self.ot_control.disconnect()
        self.td_control.disconnect()

    def end_of_protocol(self):
        self.go_to_deck_slot('3')
        self.disconnect_all()
            
def test():
    myApp = Coordinator()
    
    tc_mod = myApp.prot_context.load_module('thermocycler module', '7')
    
    tc_mod.close_lid()
    # print(platform.system())
    # myApp.go_to_deck_slot('6')
    # myApp.close_lid()
    # myApp.set_block_temp(4, 5)
    # myApp.set_syringe_model("HAMILTON_175")
    # myApp.home_all_motors()
    # myApp.manual_control()
    # myApp.go_to_position([200, Y_MIN, 40 ])

if __name__ == "__main__":
    test()