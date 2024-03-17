import os
import sys
import traceback
import copy

from PySide2 import QtCore, QtGui, QtWidgets

from shiboken2 import wrapInstance

import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMaya as om
import maya.OpenMayaUI as omui


class BPlayblast(QtCore.QObject):

    VERSION = "0.0.1"

    DEFAULT_FFMPEG_PATH = ""
    DEFAULT_CAMERA = None
    DEFAULT_RESOLUTION = "Render"
    DEFAULT_FRAME_RANGE = "Render"

    DEFAULT_CONTAINER = "mp4"
    DEFAULT_ENCODER = "h264"
    DEFAULT_H264_QUALITY = "High"
    DEFAULT_H264_PRESET = "fast"
    DEFAULT_IMAGE_QUALITY = 100

    DEFAULT_PADDING = 4

    DEFAULT_VISIBILITY = "Viewport"

    RESOLUTION_LOOKUP = {
        "Render":(),
        "HD 1080": (1920, 1080),
        "HD 720": (1280, 720),
        "HD 540": (960, 540)
    }

    FRAME_RANGE_PRESETS = [
        "Render",
        "Playback",
        "Animation"
    ]

    VIDEO_ENCODER_LOOKUP = {
        "mov": ["h264"],
        "mp4": ["h264"],
        "Image": ["jpg", "png", "tif"]
    }

    H264_QUALITIES = {
        "Very high": 18,
        "High": 20,
        "Medium": 23,
        "Low": 26
    }

    H264_PRESETS = [
        "veryslow",
        "slow",
        "medium",
        "fast",
        "faster",
        "ultrafast"
    ]

    VIEWPORT_VISIBILITY_LOOKUP = [
        ["Controllers", "controllers"],
        ["NURBS Curves", "nurbsCurves"],
        ["NURBS Surfaces", "nurbsSurfaces"],
        ["NURBS CVs", "cv"],
        ["NURBS Hulls", "hulls"],
        ["Polygons", "polymeshes"],
        ["Subdiv Surfaces", "subdivSurfaces"],
        ["Planes", "planes"],
        ["Lights", "lights"],
        ["Cameras", "cameras"],
        ["Image Planes", "imagePlane"],
        ["Joints", "joints"],
        ["IK Handles", "ikHandles"],
        ["Deformers", "deformers"],
        ["Dynamics", "dynamics"],
        ["Particle Instancers", "particleInstancers"],
        ["Fluids", "fluids"],
        ["Hair Systems", "hairSystems"],
        ["Follicles", "follicles"],
        ["nCloths", "nCloths"],
        ["nParticles", "nParticles"],
        ["nRigids", "nRigids"],
        ["Dynamic Constraints", "dynamicConstraints"],
        ["Locators", "locators"],
        ["Dimensions", "dimensions"],
        ["Pivots", "pivots"],
        ["Handles", "handles"],
        ["Texture Placements", "textures"],
        ["Strokes", "strokes"],
        ["Motion Trails", "motionTrails"],
        ["Plugin Shapes", "pluginShapes"],
        ["Clip Ghosts", "clipGhosts"],
        ["Grease Pencil", "greasePencils"],
        ["Grid", "grid"],
        ["HUD", "hud"],
        ["Hold-Outs", "hos"],
        ["Selection Highlighting", "sel"],
    ]

    VIEWPORT_VISIBILITY_PRESETS = {
        "Viewport": [],
        "Geo": ["NURBS Surfaces", "Polygons"],
        "Dynamics": ["NURBS Surfaces", "Polygons", "Dynamics", "Fluids", "nParticles"]
    }

    output_logged = QtCore.Signal(str)

    def __init__(self, ffmpeg_path=None, log_to_maya=True):

        super(BPlayblast, self).__init__()

        self.set_ffmpeg_path(ffmpeg_path)
        self.set_maya_logging_enabled(log_to_maya)

        self.set_camera(BPlayblast.DEFAULT_CAMERA)
        self.set_resolution(BPlayblast.DEFAULT_RESOLUTION)
        self.set_frame_range(BPlayblast.DEFAULT_FRAME_RANGE)

        self.set_encoding(BPlayblast.DEFAULT_CONTAINER, BPlayblast.DEFAULT_ENCODER)
        self.set_h264_settings(BPlayblast.DEFAULT_H264_QUALITY, BPlayblast.DEFAULT_H264_PRESET)
        self.set_image_settings(BPlayblast.DEFAULT_IMAGE_QUALITY)

        self.set_visibility(BPlayblast.DEFAULT_VISIBILITY)

        self.initialize_ffmpeg_process()

    def set_maya_logging_enabled(self, enabled):
        self._log_to_maya = enabled

    def log_error(self, text):
        if self._log_to_maya:
            om.MGlobal.displayError("[BPlayblast] {0}".format(text))

        self.output_logged.emit("[ERROR] {0}".format(text))

    def log_warning(self, text):
        if self._log_to_maya:
            om.MGlobal.displayWarning("[BPlayblast] {0}".format(text))

        self.output_logged.emit("[WARNING] {0}".format(text))

    def log_output(self, text):
        if self._log_to_maya:
            om.MGlobal.displayInfo(text)

        self.output_logged.emit(text)

    def set_ffmpeg_path(self, ffmpeg_path):
        if ffmpeg_path:
            self._ffmpeg_path = ffmpeg_path
        else:
            self._ffmpeg_path = BPlayblast.DEFAULT_FFMPEG_PATH

    def get_ffmpeg_path(self):
        return self._ffmpeg_path

    def validate_ffmpeg(self):
        if not self._ffmpeg_path:
            self.log_error("ffmpeg executable path not set")
            return False
        elif not os.path.exists(self._ffmpeg_path):
            self.log_error(f"ffmpeg executable path does not exists: {self._ffmpeg_path}")
            return False
        elif os.path.isdir(self._ffmpeg_path):
            self.log_error(f"Invalid ffmpeg path: {self._ffmpeg_path}")
            return False

        return True
    
    def initialize_ffmpeg_process(self):
        self._ffmpeg_process = QtCore.QProcess()
        self._ffmpeg_process.readyReadStandardError.connect(self.process_ffmpeg_output)
    
    def execute_ffmpeg_cmd(self, command):
        self._ffmpeg_process.start(command)
        if self._ffmpeg_process.waitForStarted():
            while self._ffmpeg_process.state() != QtCore.QProcess.NotRunning:
                QtCore.QCoreApplication.processEvents()
                QtCore.QThread.usleep(10)

    def process_ffmpeg_output(self):
        byte_array_output = self._ffmpeg_process.readAllStandardError()

        if sys.version_info.major < 3:
            output = str(byte_array_output)
        else:
            output = str(byte_array_output, "utf-8")
        
        self.log_output(output)
    
    def encode_h264(self, source_path, output_path, start_frame):
        frame_rate = self.get_frame_rate()

        audio_file_path, audio_frame_offset = self.get_audio_attributes()
        if audio_file_path:
            audio_offset = self.get_audio_offset_in_sec(start_frame, audio_frame_offset, frame_rate)

        crf = BPlayblast.H264_QUALITIES[self._h264_quality]
        preset = self._h264_preset

        ffmpeg_cmd = self._ffmpeg_path
        ffmpeg_cmd += f' -y -framerate {frame_rate} -i "{source_path}"'

        if audio_file_path:
            ffmpeg_cmd += f' -ss {audio_offset} -i "{audio_file_path}"'
        
        ffmpeg_cmd += f' -c:v libx264 -crf:v {crf} -preset:v {preset} -profile high -level 4.0 -pix_fmt yuv420p'

        if audio_file_path:
            ffmpeg += f' -filter_complex "[1:0] apad" -shortest'

        ffmpeg_cmd += f' "{output_path}"'

        self.log_output(ffmpeg_cmd)

        self.execute_ffmpeg_cmd(ffmpeg_cmd)

    def get_frame_rate(self):
        rate_str = cmds.currentUnit(q=True, time=True)

        if rate_str == "game":
            frame_rate = 15.0
        elif rate_str == "film":
            frame_rate = 24.0
        elif rate_str == "pal":
            frame_rate = 25.0
        elif rate_str == "ntsc":
            frame_rate = 30.0
        elif rate_str == "show":
            frame_rate = 48.0
        elif rate_str == "palf":
            frame_rate = 50.0
        elif rate_str == "ntscf":
            frame_rate = 60.0
        elif rate_str.endswith("fps"):
            frame_rate = float(rate_str[0:-3])
        else:
            raise RuntimeError("Unsupported frame rate: {0}".format(rate_str))
        
        return frame_rate
    
    def get_audio_attributes(self):
        sound_node = mel.eval("timeControl -q -sound $gPlayBackSlider;")
        if sound_node:
            file_path = cmds.getAttr(f"{sound_node}.filename")
            file_info = QtCore.QFileInfo(file_path)
            if file_info.exists():
                offset = cmds.getAttr(f"{sound_node}.offset")
                return (file_path, offset)
            
        else:
            return (None, None)

    def get_audio_offset_in_sec(self, start_frame, audio_frame_offset, frame_rate):
        return (start_frame - audio_frame_offset) / frame_rate

    def remove_temp_dir(self, temp_dir_path):
        playblast_dir = QtCore.QDir(temp_dir_path)
        playblast_dir.setNameFilters(["*.png"])
        playblast_dir.setFilter(QtCore.QDir.Files)

        for file in playblast_dir.entryList():
            playblast_dir.remove(file)

        if not playblast_dir.rmdir(temp_dir_path):
            self.log_warning(f"Failed to remove temporary directory: {temp_dir_path}")

    def open_in_viewer(self, path):
        if not os.path.exists(path):
            self.log_error(f"Failed to open in viewer. File does not exists : {path}")
            return
        
        if self._container_format in ("mov", "mp4") and cmds.optionVar(exists="PlayblastCmdQuicktime"):
            executable_path = cmds.optionVar(q="PlayblastCmdQuicktime")
            if executable_path:
                QtCore.QProcess.startDetached(executable_path, [path])
                return
            
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def set_resolution(self, resolution):
        self._resolution_preset = None

        try:
            width_height = self.preset_to_resolution(resolution)
            self._resolution_preset = resolution
        except:
            width_height = resolution

        valid_resolution = True
        try:
            if not (isinstance(width_height[0], int) and isinstance(width_height[1], int)):
                valid_resolution = False
        except:
            valid_resolution = False

        if valid_resolution:
            if width_height[0] <= 0 or width_height[1] <= 0:
                self.log_error(f"Invalid resolution: {width_height}. Values must be greater than zero.")
                return
        else:
            presets = [f"'{preset}'" for preset in BPlayblast.RESOLUTION_LOOKUP.keys()]
            self.log_error(f"Invalid resolution: {width_height}. Expected one of [int, int], {', '.join(presets)}")
            return
        
        self._width_height = (width_height[0], width_height[1])

    def get_resolution_width_height(self):
        if self._resolution_preset:
            return self.preset_to_resolution(self._resolution_preset)
        
        return self._width_height

    def preset_to_resolution(self, resolution_preset):
        if resolution_preset == "Render":
            width = cmds.getAttr("defaultResolution.width")
            height = cmds.getAttr("defaultResolution.height")
            return (width, height)
        elif resolution_preset in BPlayblast.RESOLUTION_LOOKUP.keys():
            return BPlayblast.RESOLUTION_LOOKUP[resolution_preset]
        else:
            raise RuntimeError(f"Invalid resolution preset: {resolution_preset}")
        
    def preset_to_frame_range(self, frame_range_preset):
        if frame_range_preset == "Render":
            start_frame = cmds.getAttr("defaultRenderGlobals.startFrame")
            end_frame = cmds.getAttr("defaultRenderGlobals.endFrame")
        elif frame_range_preset == "Playback":
            start_frame = int(cmds.playbackOptions(q=True, minTime=True))
            end_frame = int(cmds.playbackOptions(q=True, maxTime=True))            
        elif frame_range_preset == "Animation":
            start_frame = int(cmds.playbackOptions(q=True, animationStartTime=True))
            end_frame = int(cmds.playbackOptions(q=True, animationEndTime=True))
        else:
            raise RuntimeError(f"Invalid frame range preset: {frame_range_preset}")
        
        return (start_frame, end_frame)
    
    def set_visibility(self, visibility_data):
        if not visibility_data:
            visibility_data = []
        
        if not type(visibility_data) in [list, tuple]:
            visibility_data = self.preset_to_visibility(visibility_data)

            if visibility_data is None:
                return
            
        self._visibility = copy.copy(visibility_data)
            

    def get_visibility(self):
        if not self._visibility:
            return self.get_viewport_visibility()
        
        return self._visibility

    def preset_to_visibility(self, visibility_preset):
        if not visibility_preset in BPlayblast.VIEWPORT_VISIBILITY_PRESETS.keys():
            self.log_error(f"Invalid visibility preset: {visibility_preset}")
            return None

        preset_names = BPlayblast.VIEWPORT_VISIBILITY_PRESETS[visibility_preset]

        visibility_data = []

        if preset_names:
            for lookup_item in BPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
                visibility_data.append(lookup_item[0] in preset_names)

        return visibility_data
    
    def set_encoding(self, container_format, encoder):
        if container_format not in (containers := BPlayblast.VIDEO_ENCODER_LOOKUP.keys()):
            self.log_error(f"Invalid container: {container_format}. Expected one of {containers}")
        
        if encoder not in (encoders := BPlayblast.VIDEO_ENCODER_LOOKUP[container_format]):
            self.log_error(f"Invalid encoder: {encoder}. Expected one of {encoders}")

        self._container_format = container_format
        self._encoder = encoder

    def set_h264_settings(self, quality, preset):
        if not quality in (h264_qualities := BPlayblast.H264_QUALITIES.keys()):
            self.log_error(f"Invalid h264 quality: {quality}. Expected of {h264_qualities}")
            return
        
        if preset not in (h264_presets := BPlayblast.H264_PRESETS):
            self.log_error(f"Invalid h264 preset: {preset}. Expected of {h264_presets}")
            return
        
        self._h264_quality = quality
        self._h264_preset = preset

    def get_h264_settings(self):
        return {
            "quality": self._h264_quality,
            "preset": self._h264_preset
        }

    def set_image_settings(self, quality):
        if 0 < quality <= 100:
            self._image_quality = quality
        else:
            self.log_error(f"Invalid image quality: {quality}. Expected value betwenn 1-100")

    def get_image_settings(self):
        return {
            "quality": self._image_quality
        }
 
    def set_frame_range(self, frame_range):
        resolve_frame_range = self.resolve_frame_range(frame_range)
        if not resolve_frame_range:
            return
        
        self._frame_range_preset = None
        if frame_range in BPlayblast.FRAME_RANGE_PRESETS:
            self._frame_range_preset = frame_range
        
        self._start_frame = resolve_frame_range[0]
        self._end_frame = resolve_frame_range[1]

    def get_start_end_frame(self):
        if self._frame_range_preset:
            return self.preset_to_frame_range(self._frame_range_preset)
        
        return (self._start_frame, self._end_frame)

    def set_camera(self,  camera):  
        if camera and camera not in cmds.listCameras():
            self.log_error(f"Camera does not exist: {camera}")
            camera = None

        self._camera = camera
    
    def set_active_camera(self, camera_name):
        model_panel = self.get_viewport_panel()
        if model_panel:
            mel.eval(f"lookThroughModelPanel {camera_name} {model_panel}")
        else:
            self.log_error("Failed to set active camera. A viewport is not active.")

    def get_active_camera(self):
        model_panel = self.get_viewport_panel()
        if not model_panel:
            self.log_error("Failed to get active camera. A viewport is not active.")
            return None
        
        return cmds.modelPanel(model_panel, q=True, camera=True) # returns the camera name for a given model_panel

    def get_viewport_panel(self):
        model_panel = cmds.getPanel(withFocus=True) # dans la liste de panel, returns active view panel's name
        try:
            cmds.modelPanel(model_panel, q=True, modelEditor=True)
            return model_panel
        except:
            self.log_error("Failed to get active view")

    def get_scene_name(self):
        scene_name = cmds.file(q=True, sceneName=True, shortName=True)
        if scene_name:
            scene_name = os.path.splitext(scene_name)[0]
        else:
            scene_name = "untitled"

        return scene_name

    def get_project_dir_path(self):
        return cmds.workspace(q=True, rootDirectory=True)
    
    def get_viewport_visibility(self):
        model_panel = self.get_viewport_panel()
        if not model_panel:
            self.log_error("Failed to get viewport visibility. A viewport is not active")
            return None
        
        viewport_visibility = []
        try:
            for item in BPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
                kwargs = {item[1]: True}
                viewport_visibility.append(cmds.modelEditor(model_panel, q=True, **kwargs))
        except:
            traceback.print_exc()
            self.log_error("Failed to get active viewport visibility. See script editor.")
            return None

        return viewport_visibility

    def set_viewport_visibility(self, model_editor, visibility_flags):
        cmds.modelEditor(model_editor, e=True, **visibility_flags)

    def create_viewport_visibility_flags(self, visibility_data):
        visibility_flags = {}

        data_index = 0
        for item in BPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
            visibility_flags[item[1]] = visibility_data[data_index]
            data_index += 1

        return visibility_flags

    def resolve_output_directory_path(self, dir_path):
        if "{project}" in dir_path:
            dir_path = dir_path.replace("{project}", self.get_project_dir_path())

        return dir_path
    
    def resolve_output_filename(self, filename):
        if "{scene}" in filename:
            filename = filename.replace("{scene}", self.get_scene_name())

        return filename

    def resolve_frame_range(self, frame_range):
        try:
            if type(frame_range) in [list, tuple]:
                start_frame = frame_range[0]
                end_frame = frame_range[1]
            else:
                start_frame, end_frame = self.preset_to_frame_range(frame_range)

            return [start_frame, end_frame]

        except:
            presets = [f"'{preset}'" for preset in BPlayblast.FRAME_RANGE_PRESETS]
            self.log_error(f"Invalid frame range. Expected one of (start_frame, end_frame) or {', '.join(presets)}")

            return None
        
    def requires_ffmpeg(self):
        return self._container_format != "Image"

    def execute(self, output_dir, filename, padding=4, show_ornaments=True, show_in_viewer=True, overwrite=False):
        if self.requires_ffmpeg() and not self.validate_ffmpeg():
            self.log_error("ffmpeg executable is not configured. See script editor for details.")
            return
        
        viewport_model_panel = self.get_viewport_panel()
        if not viewport_model_panel:
            self.log_error("An active viewport is not selected. Select the viewport and retry")
            return

        if not output_dir:
            self.log_error("Output directory path not set")
            return
        if not filename:
            self.log_error("Output file name not set")
            return

        output_dir = self.resolve_output_directory_path(output_dir)
        filename = self.resolve_output_filename(filename)
        
        if padding <= 0:
            padding = BPlayblast.DEFAULT_PADDING

        if self.requires_ffmpeg():
            output_path = os.path.normpath(os.path.join(output_dir, f"{filename}.{self._container_format}"))
            if not overwrite and os.path.exists(output_path):
                self.log_error(f"Output file already exists. Enable overwrite to ignore.")
                return

            playblast_output_dir = f"{output_dir}/playblast_temp"
            playblast_output = os.path.normpath(os.path.join(playblast_output_dir, filename))
            force_overwrite = True
            compression = "png"
            image_quality = 100
            index_from_zero = True
            viewer = False

        else:
            playblast_output = os.path.normpath(os.path.join(output_dir, filename))
            force_overwrite = overwrite
            compression = self._encoder
            image_quality = self._image_quality
            index_from_zero = False
            viewer = show_in_viewer 

        width_height = self.get_resolution_width_height()
        start_frame, end_frame = self.get_start_end_frame()
        
        options = {
            "filename": playblast_output,
            "widthHeight": width_height,
            "percent": 100,
            "startTime": start_frame,
            "endTime": end_frame,
            "clearCache": True,
            "forceOverwrite": force_overwrite,
            "format": "image",
            "compression": compression,
            "quality": image_quality,
            "indexFromZero": index_from_zero,
            "framePadding": padding,
            "showOrnaments": show_ornaments,
            "viewer": viewer
        }

        self.log_output(f"Playblast options: {options}")

        # Store original viewport settings
        orig_camera = self.get_active_camera()

        camera = self._camera
        if not camera:
            camera = orig_camera

        if not camera in cmds.listCameras():
            self.log_error(f"Camera does not exists: {camera}")
            return
        
        self.set_active_camera(camera)

        orig_visibility_flags = self.create_viewport_visibility_flags(self.get_viewport_visibility())
        playblast_visibility_flags = self.create_viewport_visibility_flags(self.get_visibility())

        model_editor = cmds.modelPanel(viewport_model_panel, q=True, modelEditor=True)
        self.set_viewport_visibility(model_editor, playblast_visibility_flags)

        playblast_failed = False
        try:
            cmds.playblast(**options)
        except:
            traceback.print_exc()
            self.log_error("Failed to created playblast. See script editor for details")
            playblast_failed = True
        finally:
            # Restore original viewport settings
            self.set_active_camera(orig_camera)
            self.set_viewport_visibility(model_editor, orig_visibility_flags)

        if playblast_failed:
            return
        
        if self.requires_ffmpeg():
            source_path = f"{playblast_output_dir}/{filename}.%0{padding}d.png"

            if self._encoder == "h264":
                self.encode_h264(source_path, output_path, start_frame)
            else:
                self.log_error(f"Encoding failed. Unsupported encoder ({self._encoder}) for container ({self._container_format})")
                self.remove_temp_dir(playblast_output_dir)
                return
            
            self.remove_temp_dir(playblast_output_dir)

            if show_in_viewer:
                self.open_in_viewer(output_path)

class BPlayblastSettingsDialog(QtWidgets.QDialog):

    def __init__(self, parent):
        super(BPlayblastSettingsDialog, self).__init__(parent)

        self.setWindowTitle("Settings")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(360)
        self.setModal(True)

        self.ffmpeg_path_le = QtWidgets.QLineEdit()
        self.ffmpeg_path_select_btn = QtWidgets.QPushButton("...")
        self.ffmpeg_path_select_btn.setFixedSize(24, 19)
        self.ffmpeg_path_select_btn.clicked.connect(self.select_ffmpeg_executable)

        ffmpeg_layout = QtWidgets.QHBoxLayout()
        ffmpeg_layout.setSpacing(4)
        ffmpeg_layout.addWidget(self.ffmpeg_path_le)
        ffmpeg_layout.addWidget(self.ffmpeg_path_select_btn)

        ffmpeg_grp = QtWidgets.QGroupBox("FFmpeg Path")
        ffmpeg_grp.setLayout(ffmpeg_layout)

        self.accept_btn = QtWidgets.QPushButton("Accept")
        self.accept_btn.clicked.connect(self.accept)

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.accept_btn)
        button_layout.addWidget(self.cancel_btn)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        main_layout.addWidget(ffmpeg_grp)
        main_layout.addStretch()
        main_layout.addLayout(button_layout)

    def set_ffmpeg_path(self, path):
        self.ffmpeg_path_le.setText(path)

    def get_ffmpeg_path(self):
        return self.ffmpeg_path_le.text()

    def select_ffmpeg_executable(self):
        current_path = self.ffmpeg_path_le.text()

        new_path = QtWidgets.QFileDialog.getOpenFileName(self, "Select FFmpeg Executable", current_path)[0]
        if new_path:
            self.ffmpeg_path_le.setText(new_path)

class BPlayblastUi(QtWidgets.QDialog):

    TITLE = "BPlayblast"


    def __init__(self):
        if sys.version_info.major < 3:
            maya_main_window = wrapInstance(long(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
        else:
            maya_main_window = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

        super(BPlayblastUi, self).__init__(maya_main_window)

        self.setWindowTitle(BPlayblastUi.TITLE)
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(500)

        self._playblast = BPlayblast()

        self.load_settings()

        self._settings_dialog = None

        self.create_actions()
        self.create_menus()
        self.create_widgets()
        self.create_layout()
        self.create_connections()

        self.append_output(f"BPlayblast v{BPlayblast.VERSION}")

    def create_actions(self):
        self.save_defaults_action = QtWidgets.QAction("Save Defaults", self)
        self.save_defaults_action.triggered.connect(self.save_defaults)

        self.load_defaults_action = QtWidgets.QAction("Load Defaults", self)
        self.load_defaults_action.triggered.connect(self.load_defaults)

        self.show_settings_action = QtWidgets.QAction("Settings...", self)
        self.show_settings_action.triggered.connect(self.show_settings_dialog)

        self.show_about_action = QtWidgets.QAction("About", self)
        self.show_about_action.triggered.connect(self.show_about_dialog)

    def create_menus(self):
        self.main_menu = QtWidgets.QMenuBar()

        edit_menu = self.main_menu.addMenu("Edit")
        edit_menu.addAction(self.save_defaults_action)
        edit_menu.addAction(self.load_defaults_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.show_settings_action)

        help_menu = self.main_menu.addMenu("Help")
        help_menu.addAction(self.show_about_action)

    def create_widgets(self):
        self.output_dir_path_le = QtWidgets.QLineEdit()
        self.output_dir_path_le.setPlaceholderText("{project}/movies")

        self.output_dir_path_select_btn = QtWidgets.QPushButton("...")
        self.output_dir_path_select_btn.setFixedSize(24, 19)
        self.output_dir_path_select_btn.setToolTip("Select Output Directory")

        self.output_dir_path_show_folder_btn = QtWidgets.QPushButton(QtGui.QIcon(":fileOpen.png"), "")
        self.output_dir_path_show_folder_btn.setFixedSize(24, 19)
        self.output_dir_path_show_folder_btn.setToolTip("Show in Folder")

        self.output_filename_le = QtWidgets.QLineEdit()
        self.output_filename_le.setPlaceholderText("{scene}")
        self.output_filename_le.setMaximumWidth(200)
        self.force_overwrite_cb = QtWidgets.QCheckBox("Force overwrite")

        self.resolution_select_cmb = QtWidgets.QComboBox()

        self.resolution_width_sb = QtWidgets.QSpinBox()
        self.resolution_width_sb.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.resolution_width_sb.setRange(1, 9999)
        self.resolution_width_sb.setMinimumWidth(40)
        self.resolution_width_sb.setAlignment(QtCore.Qt.AlignRight)
        self.resolution_height_sb = QtWidgets.QSpinBox()
        self.resolution_height_sb.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.resolution_height_sb.setRange(1, 9999)
        self.resolution_height_sb.setMinimumWidth(40)
        self.resolution_height_sb.setAlignment(QtCore.Qt.AlignRight)

        self.camera_select_cmb = QtWidgets.QComboBox()
        self.camera_select_hide_defaults_cb = QtWidgets.QCheckBox("Hide defaults")

        self.frame_range_cmb = QtWidgets.QComboBox()

        self.frame_range_start_sb = QtWidgets.QSpinBox()
        self.frame_range_start_sb.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.frame_range_start_sb.setRange(-9999, 9999)
        self.frame_range_start_sb.setMinimumWidth(40)
        self.frame_range_start_sb.setAlignment(QtCore.Qt.AlignRight)

        self.frame_range_end_sb = QtWidgets.QSpinBox()
        self.frame_range_end_sb.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.frame_range_end_sb.setRange(-9999, 9999)
        self.frame_range_end_sb.setMinimumWidth(40)
        self.frame_range_end_sb.setAlignment(QtCore.Qt.AlignRight)

        self.encoding_container_cmb = QtWidgets.QComboBox()

        self.encoding_video_codec_cmb = QtWidgets.QComboBox()
        self.encoding_video_codec_settings_btn = QtWidgets.QPushButton("Settings...")
        self.encoding_video_codec_settings_btn.setFixedHeight(19)

        self.visibility_cmb = QtWidgets.QComboBox()

        self.visibility_customize_btn = QtWidgets.QPushButton("Customize...")
        self.visibility_customize_btn.setFixedHeight(19)

        self.ornaments_cb = QtWidgets.QCheckBox()
        self.ornaments_cb.setChecked(True)

        self.viewer_cb = QtWidgets.QCheckBox()
        self.viewer_cb.setChecked(True)

        self.output_edit = QtWidgets.QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setWordWrapMode(QtGui.QTextOption.NoWrap)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.playblast_btn = QtWidgets.QPushButton("Playblast")
        self.close_btn = QtWidgets.QPushButton("Close")

    def create_layout(self):
        output_path_layout = QtWidgets.QHBoxLayout()
        output_path_layout.setSpacing(4)
        output_path_layout.addWidget(self.output_dir_path_le)
        output_path_layout.addWidget(self.output_dir_path_select_btn)
        output_path_layout.addWidget(self.output_dir_path_show_folder_btn)

        output_file_layout = QtWidgets.QHBoxLayout()
        output_file_layout.setSpacing(4)
        output_file_layout.addWidget(self.output_filename_le)
        output_file_layout.addWidget(self.force_overwrite_cb)

        output_layout = QtWidgets.QFormLayout()
        output_layout.setSpacing(4)
        output_layout.addRow("Directory:", output_path_layout)
        output_layout.addRow("Filename:", output_file_layout)

        output_grp = QtWidgets.QGroupBox("Output")
        output_grp.setLayout(output_layout)

        camera_options_layout = QtWidgets.QHBoxLayout()
        camera_options_layout.setSpacing(4)
        camera_options_layout.addWidget(self.camera_select_cmb)
        camera_options_layout.addWidget(self.camera_select_hide_defaults_cb)

        resolution_layout = QtWidgets.QHBoxLayout()
        resolution_layout.setSpacing(4)
        resolution_layout.addWidget(self.resolution_select_cmb)
        resolution_layout.addWidget(self.resolution_width_sb)
        resolution_layout.addWidget(QtWidgets.QLabel("x"))
        resolution_layout.addWidget(self.resolution_height_sb)

        frame_range_layout = QtWidgets.QHBoxLayout()
        frame_range_layout.setSpacing(4)
        frame_range_layout.addWidget(self.frame_range_cmb)
        frame_range_layout.addWidget(self.frame_range_start_sb)
        frame_range_layout.addWidget(self.frame_range_end_sb)

        encoding_layout = QtWidgets.QHBoxLayout()
        encoding_layout.setSpacing(4)
        encoding_layout.addWidget(self.encoding_container_cmb)
        encoding_layout.addWidget(self.encoding_video_codec_cmb)
        encoding_layout.addWidget(self.encoding_video_codec_settings_btn)

        visibility_layout = QtWidgets.QHBoxLayout()
        visibility_layout.setSpacing(4)
        visibility_layout.addWidget(self.visibility_cmb)
        visibility_layout.addWidget(self.visibility_customize_btn)

        options_layout = QtWidgets.QFormLayout()
        options_layout.addRow("Camera:", camera_options_layout)
        options_layout.addRow("Resolution:", resolution_layout)
        options_layout.addRow("Frame Range:", frame_range_layout)
        options_layout.addRow("Encoding:", encoding_layout)
        options_layout.addRow("Visiblity:", visibility_layout)
        options_layout.addRow("Ornaments:", self.ornaments_cb)
        options_layout.addRow("Show in Viewer:", self.viewer_cb)

        options_grp = QtWidgets.QGroupBox("Options")
        options_grp.setLayout(options_layout)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.clear_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.playblast_btn)
        button_layout.addWidget(self.close_btn)

        status_bar_layout = QtWidgets.QHBoxLayout()
        status_bar_layout.addStretch()
        status_bar_layout.addWidget(QtWidgets.QLabel("v{0}".format(BPlayblast.VERSION)))


        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        main_layout.setMenuBar(self.main_menu)
        main_layout.addWidget(output_grp)
        main_layout.addWidget(options_grp)
        main_layout.addWidget(self.output_edit)
        main_layout.addLayout(button_layout)
        main_layout.addLayout(status_bar_layout)

    def create_connections(self):
        self.output_dir_path_select_btn.clicked.connect(self.select_output_directory)
        self.output_dir_path_show_folder_btn.clicked.connect(self.open_output_directory)

        self.camera_select_cmb.currentTextChanged.connect(self.on_camera_changed)
        self.camera_select_hide_defaults_cb.toggled.connect(self.refresh_cameras)

        self.frame_range_cmb.currentTextChanged.connect(self.refresh_frame_range)
        self.frame_range_start_sb.valueChanged.connect(self.on_frame_range_changed)
        self.frame_range_end_sb.valueChanged.connect(self.on_frame_range_changed)

        self.encoding_container_cmb.currentTextChanged.connect(self.refresh_video_encoders)
        self.encoding_video_codec_cmb.currentTextChanged.connect(self.on_video_encoder_changed)
        self.encoding_video_codec_settings_btn.clicked.connect(self.show_encoder_settings_dialog)

        self.resolution_select_cmb.currentTextChanged.connect(self.refresh_resolution)
        self.resolution_width_sb.valueChanged.connect(self.on_resolution_changed)
        self.resolution_height_sb.valueChanged.connect(self.on_resolution_changed)

        self.visibility_cmb.currentTextChanged.connect(self.on_visibility_preset_changed)
        self.visibility_customize_btn.clicked.connect(self.show_visibility_dialog)

        self.refresh_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self.output_edit.clear)
        self.playblast_btn.clicked.connect(self.do_playblast)
        self.close_btn.clicked.connect(self.close)

        self._playblast.output_logged.connect(self.append_output)

    def do_playblast(self):
        output_dir_path = self.output_dir_path_le.text()
        if not output_dir_path:
            output_dir_path = self.output_dir_path_le.placeholderText()

        filename = self.output_filename_le.text()
        if not filename:
            filename = self.output_filename_le.placeholderText()

        padding = BPlayblast.DEFAULT_PADDING

        show_ornaments = self.ornaments_cb.isChecked()
        show_in_viewer = self.viewer_cb.isChecked()
        overwrite = self.force_overwrite_cb.isChecked()

        self._playblast.execute(output_dir_path, filename, padding, show_ornaments, show_in_viewer, overwrite)

    def select_output_directory(self):
        print("TODO: select_output_directory()")

    def open_output_directory(self):
        print("TODO: open_output_directory()")

    def refresh(self):
        print("TODO: refresh()")

    def refresh_cameras(self):
        print("TODO: refresh_cameras()")

    def on_camera_changed(self):
        print("TODO: on_camera_changed()")

    def refresh_resolution(self):
        print("TODO: refresh_resolution()")

    def on_resolution_changed(self):
        print("TODO: on_resolution_changed()")

    def refresh_frame_range(self):
        print("TODO: refresh_frame_range()")

    def on_frame_range_changed(self):
        print("TODO: on_frame_range_changed()")

    def refresh_video_encoders(self):
        print("TODO: refresh_video_encoders()")

    def on_video_encoder_changed(self):
        print("TODO: on_video_encoder_changed()")

    def show_encoder_settings_dialog(self):
        print("TODO: show_encoder_settings_dialog()")

    def on_encoder_settings_dialog_modified(self):
        print("TODO: on_encoder_settings_dialog_modified()")

    def on_visibility_preset_changed(self):
        print("TODO: on_visibility_preset_changed()")

    def show_visibility_dialog(self):
        print("TODO: show_visibility_dialog()")

    def on_visibility_dialog_modified(self):
        print("TODO: on_visibility_dialog_modified()")

    def save_settings(self):
        cmds.optionVar(sv=("BPlayblastUiFFmpegPath", self._playblast.get_ffmpeg_path()))

    def load_settings(self):
        if cmds.optionVar(exists="BPlayblastUiFFmpegPath"):
            self._playblast.set_ffmpeg_path(cmds.optionVar(q="BPlayblastUiFFmpegPath"))

    def save_defaults(self):
        print("TODO: save_defaults()")

    def load_defaults(self):
        print("TODO: load_defaults()")

    def show_settings_dialog(self):
        if not self._settings_dialog:
            self._settings_dialog = BPlayblastSettingsDialog(self)
            self._settings_dialog.accepted.connect(self.on_settings_dialog_modified)

        self._settings_dialog.set_ffmpeg_path(self._playblast.get_ffmpeg_path())

        self._settings_dialog.show()

    def on_settings_dialog_modified(self):
        ffmpeg_path = self._settings_dialog.get_ffmpeg_path()
        self._playblast.set_ffmpeg_path(ffmpeg_path)

        self.save_settings()

    def show_about_dialog(self):
        text = '<h2>{0}</h2>'.format(BPlayblastUi.TITLE)
        text += '<p>Version: {0}</p>'.format(BPlayblast.VERSION)
        text += '<p>Author: Jacob Provencher</p>'
        text += '<p>Website: <a style="color:white;" href="https://jacprovjp.wixsite.com/portfolio">jacobprovencher.com</a></p><br>'

        QtWidgets.QMessageBox().about(self, "About", "{0}".format(text))

    def append_output(self, text):
        self.output_edit.appendPlainText(text)

    def keyPressEvent(self, event):
        super(BPlayblastUi, self).keyPressEvent(event)
        event.accept()


if __name__ == "__main__":

    try:
        jacob_playblast_dialog.close() # pylint: disable=E0601
        jacob_playblast_dialog.deleteLater()
    except:
        pass

    jacob_playblast_dialog = BPlayblastUi()
    jacob_playblast_dialog.show()


