
"""
WEB APP SCRIPT
    This script is the heart/brain of the system. It has an instance of Coordinator through which it sends and receives commands and 
    information respectively. It also hosts a server through which it can interface with the user, using predefined html templates 
    linked to registered server routes.
"""
RUNNING_APP_FOR_REAL = False
import cv2
import os
import time
from flask import Flask, render_template, url_for, Response, flash, request, redirect
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
from video_stream import VideoStream
from flag import Flag
import logging
if RUNNING_APP_FOR_REAL:
    from coordinator import *
from python_execute import Py_Execute

ALLOWED_EXTENSIONS = ['json']
LABWARE_CHIP = "c"
LABWARE_PLATE = "p"
LABWARE_SYRINGE = "s"
CAMERA_PORT = 0
PIPPETE_CAMERA_PORT = 1
RELATIVE_PATH_TO_PROTOCOLS_W = 'protocols\\'
RELATIVE_PATH_TO_PROTOCOLS_L = '/protocols/'
RELATIVE_PATH_TO_LABWARE_W = 'saved_labware\\'
RELATIVE_PATH_TO_LABWARE_L = '/saved_labware/'
RELATIVE_PATH_TO_SYRINGES_W = 'models\\syringes\\'
RELATIVE_PATH_TO_SYRINGES_L = '/models/syringes/'
LINUX_OS = 'posix'
WINDOWS_OS = 'nt'
TEMP = 0
HOLD_TIME = 1
X, Y, Z = 0, 1 ,2
NUMBER_OF_CALIBRATION_POINTS = 3
FOURTH_CALIBRATION_POINT_POSITION = 3
LABWARE_COMPONENT_INDEX = 0 # 'c' or 'p'
COMPONENT_MODEL_INDEX = 1
SETTING_NAME_INDEX = 0
NEW_VALUE_INDEX = 1

app = Flask(__name__)

print("Running web_app.py")

# -----------------------------------
# This section gets rid of console messages from the server (that way we don't loose error messages from the system in development after a long run time)
app.logger.disabled = True
log = logging.getLogger('werkzeug')
log.disabled = True
logging.getLogger("socketio").setLevel(logging.ERROR)
logging.getLogger("engineio").setLevel(logging.ERROR)

# -----------------------------------

if RUNNING_APP_FOR_REAL:
    coordinator = Coordinator()
socketio = SocketIO(app, cors_allowed_origins='*') # the second parameter allows to disable some extra security implemented by newer versions of Flask that create an error if this parameter is not added

executer = Py_Execute()
myCamera = VideoStream(CAMERA_PORT)
my_Pippete_Camera = VideoStream(PIPPETE_CAMERA_PORT)
sending_syringe = Flag()
done_calibration_flag = Flag()
componentToCalibrate = []
if RUNNING_APP_FOR_REAL:
    app.config['UPLOAD_CHIP_FOLDER'] = coordinator.get_component_models_location(LABWARE_CHIP) # Establishes path to save uploads of chip models
    app.config['UPLOAD_PLATE_FOLDER'] = coordinator.get_component_models_location(LABWARE_PLATE) # Establishes path to save uploads of plate models
    app.config['UPLOAD_SYRINGE_FOLDER'] = coordinator.get_component_models_location(LABWARE_SYRINGE) # Establishes path to save uploads of syringe models
app.config['MAX_CONTENT_LENGTH'] = 1024*1024 # Limit file limit to 1 MB
app.secret_key = "hola"

"""
------------------------------------------------ ROUTES FOR FLASK APP
    This section defines the different routes of the app
"""

@app.route('/')
@app.route('/home')
def home():
    return render_template("home.html")

@app.route('/manual_control')
def manual_control():
    return render_template("manual_control.html")

@app.route('/calibrate_component')
def calibrate_component():
    print("calibrate_component")
    return render_template("calibration.html")

@app.route('/load_calibration')
def load_component_calibration():
    return render_template("load_calibration.html")

@app.route('/instantaneous_commands')
def instant_commands():
    return render_template("instant_command.html")

@app.route('/labware')
def labware():
    return render_template("labware.html")

@app.route('/labware/add')
def add_labware():
    return render_template("add_labware.html")

@app.route('/labware/create_model')
def create_labware_model():
    return render_template("labware_creation.html")

@app.route('/save_labware_setup')
def save_labware_setup():
    return render_template("save_labware_setup.html")

@app.route('/load_labware_setup')
def load_labware_setup():
    return render_template("load_labware_setup.html")

@app.route('/script')
def script():
    return render_template("script.html")

@app.route('/settings')
def system_settings():
    return render_template("settings.html")
    
# This method checks to see if the filename ends with an allowed extension
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_new_model', methods=["GET", "POST"])
def upload_new_model():
    # The route can be accessed with either a GET request or a POST request (if it's just a GET, it will only return the basic template)
    if request.method == "POST":
        if request.files: # If there is a files object sent along with the request
            document = request.files["modelFile"] # Select the file from the files dictionary
            # If no file is uploaded but they still hit submit, the request will have a file, but it will be empty
            if document.filename == '':
                flash('No selected file')
                return redirect(request.url)
            # This will check for presence of a file again and for the appropriate extension
            if allowed_file(document.filename):
                filename = secure_filename(document.filename)
                component_type = request.form.get('command')
                if (component_type == LABWARE_CHIP):
                    document.save(os.path.join(app.config['UPLOAD_CHIP_FOLDER'], filename)) # This saves the document to the specified path in UPLOAD_FOLDER
                elif (component_type == LABWARE_PLATE):
                    document.save(os.path.join(app.config['UPLOAD_PLATE_FOLDER'], filename)) # This saves the document to the specified path in UPLOAD_FOLDER
                elif (component_type == LABWARE_SYRINGE):
                    document.save(os.path.join(app.config['UPLOAD_SYRINGE_FOLDER'], filename)) # This saves the document to the specified path in UPLOAD_FOLDER
                
                flash(f"'{filename}' succesfully uploaded")
                return redirect(request.url) #(url_for('upload_new_model', filename=filename))
            else:
                flash(f"Wrong type of file uploaded. Only {ALLOWED_EXTENSIONS} files allowed")
                return redirect(request.url)                
    return render_template("upload_new_model.html")

def gen_1(camera):
    while True:
        if camera.stopped:
            break
        frame = camera.read()
        cam = cv2.flip(frame, -1)
        # font = cv2.FONT_HERSHEY_SIMPLEX
        # cv2.putText(frame, "hola amiguitos", (20, 100), font, 1, (255, 255, 255), 2, cv2.LINE_4)
        ret, jpeg = cv2.imencode('.jpg', cam)
        if jpeg is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
        else:
            print("frame is none")

def gen_2(camera):
    while True:
        if camera.stopped:
            break
        frame = camera.read()
        # font = cv2.FONT_HERSHEY_SIMPLEX
        # cv2.putText(frame, "hola amiguitos", (20, 100), font, 1, (255, 255, 255), 2, cv2.LINE_4)
        ret, jpeg = cv2.imencode('.jpg',frame)
        if jpeg is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
        else:
            print("frame is none")

@app.route('/video_1_feed')
def video_1_feed():
    return Response(gen_1(myCamera.start()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_2_feed')
def video_2_feed():
    return Response(gen_2(my_Pippete_Camera.start()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def text_coordinates():
    x, y, z = coordinator.get_current_coordinates() 
    return f"({x}, {y}, {z})"

def start_sending_coordinates():
    sending_syringe.activate()

def stop_sending_coordinates():
    sending_syringe.deactivate()

def still_sending():
    return sending_syringe.read()

def read_done_calibration_flag():
    return done_calibration_flag.read()

def activate_done_calibration_flag():
    done_calibration_flag.activate()

def deactivate_done_calibration_flag():
    done_calibration_flag.deactivate()

"""
------------------------------------------------ SOCKET EVENTS
    This section defines all the event handlers that get triggered from the socket
"""
#----------------------------------------------- COORDINATES EVENTS SECTION
@socketio.on("give_me_coordinates")
def deliver_coordinates():
    msg = ""
    prev = 0
    start_sending_coordinates()
    while still_sending():
        if (prev != msg):
            socketio.emit("new_coordinates", [msg])
            prev = msg
        msg = text_coordinates()
        time.sleep(coordinator.get_coordinate_refresh_rate())

@socketio.on("stop_coordinates")
def stop_deliver_coordinates():
    stop_sending_coordinates()

#----------------------------------------------- MANUAL CONTROL PAGE EVENTS SECTION
@socketio.on("start_manual_control_window")
def start_manual_control_window():
    print("Manual control")
    coordinator.ot_control.set_tc_flag(is_tc_mounted=True)
    coordinator.manual_control()

@socketio.on("stop_manual_control_window")
def stop_manual_control_window():
    print("stop_manual_control")
    coordinator.stop_manual_control()

@socketio.on("screen_info")
def screen_info():
    print("screen_info")
    coordinator.ot_control.screen_info(True)

@socketio.on("up_step_size")
def up_step_size():
    print("up_step_size")
    coordinator.up_step_size()

@socketio.on("down_step_size")
def down_step_size():
    print("down_step_size")
    coordinator.down_step_size()

#----------------------------------------------- THERMOCYCLER PAGE EVENTS SECTION

@socketio.on("open_lid")
def open_lid():
    print("open_lid")
    coordinator.open_lid()

@socketio.on("close_lid")
def close_lid():
    print("close_lid")
    coordinator.close_lid()

@socketio.on("deactivate_all")
def deactivate_all():
    print("deactivate_all")
    coordinator.deactivate_all()

@socketio.on("deactivate_lid")
def deactivate_lid():
    print("deactivate_lid")
    coordinator.deactivate_lid()

@socketio.on("deactivate_block")
def deactivate_block():
    print("deactivate_block")
    coordinator.deactivate_block()

@socketio.on("set_temperature")
def set_temperature(elements):
    coordinator.set_block_temp(elements[TEMP], elements[HOLD_TIME])

@socketio.on("set_lid_temperature")
def set_lid_temperature(temp):
    coordinator.set_lid_temp(temp)

@socketio.on("get_lid_temp")
def get_lid_temp():
    temp = coordinator.tc_control.get_lid_temp()
    socketio.emit("get_lid_temp", temp)
    
@socketio.on("get_block_temp")
def get_block_temp():
    temp = coordinator.tc_control.get_block_temp()
    socketio.emit("get_block_temp", temp)
    
@socketio.on("lid_position")
def lid_position():
    print("lid_position")
    coordinator.tc_control.lid_status()

@socketio.on("block_temperature_status")
def block_temperature_status():
    print("block_temperature_status")
    coordinator.tc_control.status()

@socketio.on("hold_time")
def hold_time():
    print("hold_time")
    coordinator.tc_control.hold_time()

#----------------------------------------------- TEMPDECK PAGE EVENTS SECTION

@socketio.on("set_tempdeck_temp")
def set_tempdeck_temp(elements):
    print("set_tempdeck_temp")
    coordinator.set_tempdeck_temp(celcius=elements[TEMP], holding_time_in_minutes=elements[HOLD_TIME])

@socketio.on("deactivate_tempdeck")
def deactivate_tempdeck():
    print("deactivate_tempdeck")
    coordinator.deactivate_tempdeck()

@socketio.on("get_tempdeck_temp")
def get_tempdeck_temp():
    print("get_tempdeck_temp")
    temp = coordinator.get_tempdeck_temp()
    socketio.emit("get_tempdeck_temp", temp)

@socketio.on("check_tempdeck_status")
def check_tempdeck_status():
    print("check_tempdeck_status")
    coordinator.check_tempdeck_status()
    status = coordinator.check_tempdeck_status()
    socketio.emit("check_tempdeck_status", status)

#----------------------------------------------- CALIBRATION EVENTS SECTION

@socketio.on("calibration_parameters")
def calibration_parameters(component_information):
    # Empty pre-existing components
    componentToCalibrate.clear()
    # component_information comes in the following format: ["c", "SZ002"]
    componentToCalibrate.append(component_information[0]) # Type of component: either "c" or "p" for chip and plate. respectively
    componentToCalibrate.append(component_information[1]) # Component model

@socketio.on("start_calibration")
def start_calibration():
    deactivate_done_calibration_flag()
    socketio.emit("component_being_calibrated", componentToCalibrate) # Send the component being calibrated
    calibration_points = []
    while not read_done_calibration_flag():
        # Enable manual control
        coordinator.manual_control()
        print("Added")
        # Once manual control is over (user pressed START button), read the position of the syringe
        position = coordinator.get_current_coordinates()
        # Store the position in the calibration points list
        calibration_points.append(position)
        # Send feedback to user
        socketio.emit("feedback_calibration_point", [ position[X], position[Y], position[Z] ] )
        # Check if all the calibration points have been collected
        if (len(calibration_points) == NUMBER_OF_CALIBRATION_POINTS):
            activate_done_calibration_flag()

    # Checking again, bc the flag could've been deactivated when exiting calibration (pressing home button or other) before finishing the calibration
    if (len(calibration_points) == NUMBER_OF_CALIBRATION_POINTS):
        # Send an event with the calibration points list
        socketio.emit("stored_calibration_points", calibration_points)

@socketio.on("start_calibration_load")
def start_calibration_load():
    socketio.emit("component_being_calibrated", componentToCalibrate) # Send the component being calibrated

@socketio.on("modify_calibration")
def modify_calibration(calibration_points):
    # The 4th element will be the index to modify
    index = calibration_points[FOURTH_CALIBRATION_POINT_POSITION]
    new_list = calibration_points[:(NUMBER_OF_CALIBRATION_POINTS - 1)] # List with the previous calibration points
    # Enable manual control
    coordinator.manual_control()
    # Once manual control is over (user pressed START button), read the position of the syringe
    new_position = coordinator.get_current_coordinates()
    # Store the position in the calibration points list
    new_list[index] = new_position

    # Send an event with the new calibration points
    socketio.emit("calibration_points", new_list)

@socketio.on("test_calibration")
def test_calibration(calibration_points):
    # Guess fourth point
    fourth_point = coordinator.guess_fourth_calibration_point(calibration_points)
    # Move syringe to the guessed point
    coordinator.go_to_position(fourth_point)

@socketio.on("good_calibration")
def calibration_confirmed(calibration_points):
    # Unpack component_information:
    labware_component = componentToCalibrate[LABWARE_COMPONENT_INDEX]
    component_model = componentToCalibrate[COMPONENT_MODEL_INDEX]

    # Call the coordinator method that creates the component and maps out its elements
    coordinator.add_labware_component(labware_component, component_model, calibration_points)

@socketio.on("stop_calibration")
def stop_calibration():
    stop_sending_coordinates()
    myCamera.stop()
    my_Pippete_Camera.stop()
    activate_done_calibration_flag()
    coordinator.stop_manual_control()

#----------------------------------------------- LABWARE EVENTS SECTION

@socketio.on("get_labware_models")
def get_labware_models():
    models = coordinator.get_available_component_models()
    socketio.emit("models_available", models)

@socketio.on("give_me_current_labware")
def get_current_labware():
    labware = coordinator.get_current_labware()
    socketio.emit("here_current_labware", labware)

@socketio.on("delete_labware")
def delete_labware(command):
    labware_type = command[LABWARE_COMPONENT_INDEX]
    labware_index = int(command[COMPONENT_MODEL_INDEX])
    coordinator.remove_labware_component(labware_type, labware_index)

@socketio.on("save_labware_setup")
def save_labware_setup(output_file_name):
    coordinator.save_labware_setup(output_file_name)

@socketio.on("load_labware_setup")
def load_labware_setup(input_file_name):
    coordinator.load_labware_setup(input_file_name)

@socketio.on("available_saved_labware_files")
def available_saved_labware():
    files_list = coordinator.get_available_labware_setup_files()
    socketio.emit("saved_labware_files", files_list)

@socketio.on("new_labware_model")
def new_labware_model(model_properties):
    if (model_properties["component_type"] == "Chip"):
        coordinator.create_new_chip_model(model_properties)

    elif (model_properties["component_type"] == "Plate"):
        coordinator.create_new_plate_model(model_properties)

    elif (model_properties["component_type"] == "Syringe"):
        coordinator.create_new_syringe_model(model_properties)

#----------------------------------------------- SETTINGS EVENTS SECTION
@socketio.on("get_current_settings")
def get_current_settings():
    current_settings= coordinator.get_current_settings()
    socketio.emit('current_settings', current_settings)

@socketio.on("updated_setting")
def update_settings(updated_setting):
    coordinator.update_setting(updated_setting[SETTING_NAME_INDEX], updated_setting[NEW_VALUE_INDEX])

@socketio.on("get_dynamic_selects_options")
def get_syringe_models():
    dynamic_selects_options = dict()
    syringe_models = coordinator.get_available_component_models()["syringes"] # The only dynamic selects component in the front end is the syringe models for now, but there could be more in the future
    dynamic_selects_options["syringe_model"] = syringe_models
    socketio.emit('dynamic_selects_options', dynamic_selects_options)

#----------------------------------------------- INSTANTANEOUS COMMANDS EVENTS SECTION

@socketio.on("instant_command")
def execute_instant_command(command_description):
    # Here goes the App.whatever that sends an instantaneous command to the OT_CONTROL object -> "INSTANTANEOUS COMMANDS" section of Application class
    if(command_description[0] == "c"):
        chip = int(command_description[1])
        well_nickname = command_description[2]
        coordinator.go_to_well(chip, well_nickname)

    else:
        plate = int(command_description[1])
        pot_nickname = command_description[2]
        coordinator.go_to_pot(plate, pot_nickname)

@socketio.on("get_labware_summary")
def get_labware_summary():
    full_labware_dict =  coordinator.get_full_current_labware()
    labware_summary = dict()
    labware_summary["chips"] = list()
    labware_summary["plates"] = list()
    """
    labware_summary format
        labware_summary = {
            "chips": [
                chip_summary#1, 
                chip_summary#2
            ],
            "plates": [
                plate_summary#1,
                plate_summary#2,
            ]
        }

        chip_summary = {
            "model": [str],
            "nicknames": [nickname_1, nickname_2, ... , nickname_n] # Like A3, B5, C11, etc.
        }

        plate_summary = {
            "model": [str],
            "nicknames": [nickname_1, nickname_2, ... , nickname_n] # Like A3, B5, C11, etc.
        }
    """
    for chip_properties in full_labware_dict["chips"]:
        summary = dict()
        summary["model"] = chip_properties["model"]
        summary["nicknames"] = chip_properties["well_nicknames"]
        labware_summary["chips"].append(summary)

    for plate_properties in full_labware_dict["plates"]:
        summary = dict()
        summary["model"] = plate_properties["model"]
        summary["nicknames"] = plate_properties["pot_nicknames"]
        labware_summary["plates"].append(summary)

    # print(f"labware_summary: {labware_summary}")
    socketio.emit("labware_summary", labware_summary)

@socketio.on("go_to_deck_slot")
def go_to_deck_slot(slot):
    print(f"Move to slot {slot}")
    coordinator.go_to_deck_slot(slot)

@socketio.on("home_all_motors")
def home_all_motors():
    coordinator.ot_control.home()

@socketio.on("home_Z")
def home_Z():
    coordinator.ot_control.home('Z')

@socketio.on("home_A")
def home_A():
    coordinator.ot_control.home('A')

@socketio.on("home_B")
def home_B():
    coordinator.ot_control.home('B')

@socketio.on("home_C")
def home_C():
    coordinator.ot_control.home('C')

@socketio.on("connect_all")
def connect_all():
    coordinator.connect_all()

#----------------------------------------------- HIGH LEVEL SCRIPT FUNCTIONS -----------------------------

#------------------WORKING WITH A PROTOCOL.PY SECTION--------------------
@socketio.on("run_protocol")
def run_protocol(protocol_name):
    # if RUNNING_APP_FOR_REAL:
    coordinator.disconnect_all() # First we disconnect all the modules
    executer.set_file_name(protocol_name) # Then we add the calibration to use
    executer.execute_python_protocol() # Then we execute an external file: the protocol.py

@socketio.on("give_me_protocol_python")
def give_me_protocol_python(protocolName):
    # read file
    if os.name == WINDOWS_OS:
        path_to_protocol = RELATIVE_PATH_TO_PROTOCOLS_W + protocolName # moves to script folder
    elif os.name == LINUX_OS:
        path_to_protocol = RELATIVE_PATH_TO_PROTOCOLS_L + protocolName # moves to script folder
    with open(path_to_protocol, 'r') as myfile:
        data = myfile.read()
    socketio.emit("protocol_python_data", data) # send data back to js in a json string

@socketio.on("get_available_protocols")
def get_available_protocols():
    if os.name == WINDOWS_OS:
        path_to_protocol = RELATIVE_PATH_TO_PROTOCOLS_W  # moves to script folder
    elif os.name == LINUX_OS:
        path_to_protocol = RELATIVE_PATH_TO_PROTOCOLS_L  # moves to script folder
    list = os.listdir(path_to_protocol) # make a list of scripts in folder
    print(list)
    socketio.emit("protocols_available", list) # send the list back to js

@socketio.on("pause_protocol")
def pause_protocol():
    print("pause_protocol")
    coordinator.pause_protocol()

#------------------WORKING WITH A CALIBRATION.JSON SECTION--------------------

@socketio.on("get_available_calibrations")
def get_available_calibrations():
    if os.name == WINDOWS_OS:
        path_to_calibration = RELATIVE_PATH_TO_LABWARE_W  # moves to script folder
    elif os.name == LINUX_OS:
        print(f"PATH: {RELATIVE_PATH_TO_LABWARE_L}")
        path_to_calibration = RELATIVE_PATH_TO_LABWARE_L  # moves to script folder
    list = os.listdir(path_to_calibration) # make a list of scripts in folder
    print(list)
    socketio.emit("calibrations_available", list) # send the list back to js

@socketio.on("set_labware_calibration")
def set_labware_calibration(calibration_file_name):
    executer.set_calibration_file_name(calibration_file_name)

@socketio.on("stop_protocol")
def stop_protocol():
    executer.stop_execution()

@socketio.on("reconnect_coordinator")
def reconnect_coordinator():
    coordinator.connect_all()

@socketio.on("get_available_syringes")
def get_available_syringes():
    if os.name == WINDOWS_OS:
        path_to_calibration = RELATIVE_PATH_TO_SYRINGES_W  # moves to script folder
    elif os.name == LINUX_OS:
        path_to_calibration = RELATIVE_PATH_TO_SYRINGES_L  # moves to script folder
    list = os.listdir(path_to_calibration) # make a list of scripts in folder
    print(list)
    socketio.emit("syringes_available", list) # send the list back to js

@socketio.on("set_labware_syringes")
def set_labware_syringes(syringes_file_name):
    executer.set_syringes_file_name(syringes_file_name)

#------------------EXTRA STUFF THAT WE DON'T NEED FOR NOW--------------------

@socketio.on("run_batch")
def run_batch():
    print("socket run batch success")

@socketio.on("hard_stop")
def hard_stop():
    # print("hard_stop")
    coordinator.hard_stop()

@socketio.on("stop_load")
def stop_load():
    # print("stop_load")
    coordinator.hard_stop()

@socketio.on("pause_batch")
def pause_batch():
    print("pause_batch")
    #coordinator.pause_batch()

@socketio.on("run_script")
def run_script():
    # print("I am running script")
    coordinator.run_batch()

@socketio.on("give_me_script_json")
def give_me_script_json(scriptName):
    # read file
    path_to_script = "../scripts/" + scriptName # moves to script folder
    with open(path_to_script, 'r') as myfile:
        data = myfile.read()

    socketio.emit("script_json_data", data) # send data back to js in a json string

@socketio.on("get_available_scripts")
def get_available_scripts():
    path_to_scripts_folder = "../scripts" # path to folder
    list = os.listdir(path_to_scripts_folder) # make a list of scripts in folder
    socketio.emit("scripts_available", list) # send the list back to js

if __name__ == "__main__":
    socketio.run(app)