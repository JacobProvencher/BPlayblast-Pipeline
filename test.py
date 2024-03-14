import maya.standalone
maya.standalone.initialize()

from maya import cmds

try:
    cmds.file(new=True, force=True)  # Create a new scene
    cube = cmds.polyCube()[0]        # Create a polygon cube and store its name
    cmds.file(rename='E:/CAREER/scripting/scenes/test_maya_standalone.ma')  # Rename the scene file
    cmds.file(save=True, type='mayaAscii')        # Save the scene as Maya ASCII
finally:
    maya.standalone.uninitialize()



