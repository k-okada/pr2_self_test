#!/usr/bin/env python
#
# Software License Agreement (BSD License)
#
# Copyright (c) 2008, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of the Willow Garage nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

##\author Kevin Watts

import roslib; roslib.load_manifest('qualification')

import rospy

import os
import sys
from datetime import datetime
import wx
import time
from wx import xrc
from wx import html

from xml.dom import minidom

from qualification.test import *
from qualification.qual_frame import *

#import traceback

#import invent_client.invent_client
#from invent_client.invent_client import Invent

#import runtime_monitor
#from runtime_monitor.monitor_panel import MonitorPanel

from roslaunch_caller import roslaunch_caller 
from roslaunch.core import RLException

TESTS_DIR = os.path.join(roslib.packages.get_pkg_dir('qualification'), 'tests')
CONFIG_DIR = os.path.join(roslib.packages.get_pkg_dir('qualification'), 'config')

def load_tests_from_map(tests, test_descripts_by_file):
  # Load test directory
  tests_xml_path = os.path.join(TESTS_DIR, 'tests.xml')
  try:
    doc = minidom.parse(tests_xml_path)
  except IOError:
    import traceback
    traceback.print_exc()
    print >> sys.stderr, "Could not load tests description from '%s'"%(tests_xml_path)
    return False  
  
  # Loads tests by serial number of part
  test_elements = doc.getElementsByTagName('test')
  for test in test_elements:
    serial = test.attributes['serial'].value
    test_file = test.attributes['file'].value
    descrip = test.attributes['descrip'].value
    if tests.has_key(serial):
      tests[serial].append(test_file)
    else:
      tests[serial] = [ test_file ]
      
    test_descripts_by_file[test_file] = descrip
    
  return True

def load_configs_from_map(config_files, config_descripts_by_file):
  # Load part configuration scripts
  config_xml_path = os.path.join(CONFIG_DIR, 'configs.xml')
  try:
    doc = minidom.parse(config_xml_path)
  except IOError:
    print >> sys.stderr, "Could not load configuation scripts from '%s'"%(config_xml_path)
    return False
    
  config_elements = doc.getElementsByTagName('config')
  for conf in config_elements:
    try:
      serial = conf.attributes['serial'].value
      file = conf.attributes['file'].value
      descrip = conf.attributes['descrip'].value
      
      powerboard = True
      if conf.attributes.has_key('powerboard'):
        powerboard = conf.attributes['powerboard'].value != "false"
    except:
      print 'Caught exception parsing configuration file'
      import traceback
      traceback.print_exc()
      return False

    # Generate test XML. If we need power board, add prestartup/shutdown
    # to turn on/off power
    test = '<test>\n'
    test += '<name>%s</name>\n' % descrip
    if powerboard:
      test += '<pre_startup name="Power Cycle">scripts/power_cycle.launch</pre_startup>\n'
    test += '<pre_startup name="%s">config/%s</pre_startup>\n' % (descrip, file)
    test += '<subtest name="%s Test">config/subtest_conf.launch</subtest>\n' % (descrip)
    if powerboard:
      test += '<shutdown name="Shutdown">scripts/power_board_disable.launch</shutdown>\n</test>'
    else:
      test += '</test>'
      
    if config_files.has_key(serial):
      config_files[serial].append(test)
    else:
      config_files[serial] = [ test ]
      
    config_descripts_by_file[test] = descrip

  return True

class ConfigObject(QualTestObject):
  def __init__(self, name, serial):
    QualTestObject.__init__(self, name, serial)
    self._config = True

## Allows user to choose which component to test and which test to run
class SerialPanel(wx.Panel):
  ##@param parent wxPanel: Parent frame
  ##@param resource: XRC resource to load panel
  ##@param qualification_frame: Qualfication frame to pass test, serial to
  def __init__(self, parent, resource, qualification_frame):
    wx.Panel.__init__(self, parent)
    
    self._manager = qualification_frame
    
    self._res = resource

    self._tests = {}
    self._test_descripts_by_file = {}
    load_tests_from_map(self._tests, self._test_descripts_by_file)

    self._configs = {}
    self._config_descripts_by_file = {}
    load_configs_from_map(self._configs, self._config_descripts_by_file)
    
    self._panel = resource.LoadPanel(self, 'serial_panel')
    self._sizer = wx.BoxSizer(wx.HORIZONTAL)
    
    self._sizer.Add(self._panel, 1, wx.EXPAND|wx.ALIGN_CENTER_VERTICAL)
    self.SetSizer(self._sizer)
    self.Layout()
    self.Fit()

    # Component qualification tab
    self._test_button = xrc.XRCCTRL(self._panel, 'test_button')
    self._serial_text = xrc.XRCCTRL(self._panel, 'serial_text')
    
    self._test_button.Bind(wx.EVT_BUTTON, self.on_test)
        
    # Config tab
    self._serial_text_conf = xrc.XRCCTRL(self._panel, 'serial_text_conf')

    self._config_button = xrc.XRCCTRL(self._panel, 'config_button')
    self._config_button.Bind(wx.EVT_BUTTON, self.on_config)

    # Starts on test cart panel
    self._notebook = xrc.XRCCTRL(self._panel, 'test_tab_control')
    self._notebook.ChangeSelection(0)

    self._panel.Bind(wx.EVT_CHAR, self.on_char)
    self._serial_text.SetFocus()
    #self._serial_text.Bind(wx.EVT_COMMAND_TEXT_ENTER, self.on_test)

  ##@todo Everything
  def on_config(self, event):
    # Get selected launch file
    serial = self._serial_text_conf.GetValue()

    # popup box
    if not self.has_conf_script(serial):
      print 'No conf script'
      return

    config_str = self.select_conf_to_load(serial)
    name = self._config_descripts_by_file[config_str]
    
    config_test = Test()
    if not config_test.load(config_str, roslib.packages.get_pkg_dir('qualification')):
      wx.MessageBox('Unable to load configuration data and parameters. Check file and try again.','Failed to load test', wx.OK|wx.ICON_ERROR, self)
      return 
    
    item = ConfigObject(name, serial)

    self._manager.begin_test(config_test, item)



 
  def has_conf_script(self, serial):
    return self._configs.has_key(serial[0:7])

  def has_test(self, serial):
    return self._tests.has_key(serial[0:7])

  def on_test(self, event):
    # Get the first 7 characters of the serial
    serial = self._serial_text.GetValue()
    
    if not self.has_test(serial):
      wx.MessageBox('No test defined for that serial number.','Error - Invalid serial number', wx.OK|wx.ICON_ERROR, self)
      return

    short_serial = serial[0:7]

    test_folder_file = self._tests[short_serial][0]
    if len(self._tests[short_serial]) > 1:
      # Load select_test_dialog to ask which test
      test_folder_file = self.select_test_to_load(short_serial)
    
    if test_folder_file is None:
      return

    # Hack to find directory of scripts
    ##\todo os.path.dirname()
    #dir, sep, test_file = test_folder_file.partition('/')
    
    test_path = os.path.join(os.path.join(TESTS_DIR, test_folder_file))
    test_dir = os.path.dirname(test_path)
    test_str = open(test_path).read()

    current_test = Test()
    if not current_test.load(test_str, test_dir):
      wx.MessageBox('Unable to load test data and parameters. Check file %s and try again.' % test_file,'Failed to load test', wx.OK|wx.ICON_ERROR, self)
      return 

    # Item
    name = self._test_descripts_by_file[test_folder_file]
    item = QualTestObject(name, serial)
  
    self._manager.begin_test(current_test, item)
 
  # Select if we have multiple, etc
  def select_string_from_list(self, msg, lst):
    # Load robot selection dialog
    dialog = self._res.LoadDialog(self, 'select_test_dialog')
    select_text = xrc.XRCCTRL(dialog, 'select_text')
    select_text.SetLabel(msg)
    test_box = xrc.XRCCTRL(dialog, 'test_list_box')
    test_box.InsertItems(lst, 0)
    test_box.SetSelection(0)
    
    select_text.Wrap(270)

    dialog.Layout()


    # return string of test folder/file to run
    if (dialog.ShowModal() == wx.ID_OK):
      desc = test_box.GetStringSelection()
      dialog.Destroy()
      return desc
    else: 
      dialog.Destroy()
      return None

  def select_conf_to_load(self, serial):
    short_serial = serial[0:7]
    
    # Load select_test_dialog
    configs_by_descrip = {}
    for conf in self._configs[short_serial]:
      configs_by_descrip[self._config_descripts_by_file[conf]] = conf
      
    msg = 'Select type to configure component.'

    descrips = dict.keys(configs_by_descrip)
    descrips.sort()
  
    choice = self.select_string_from_list(msg, descrips)
    if choice is None:
      return None
    return configs_by_descrip[choice]
    
  # If more than one test for that serial, calls up prompt to ask user to select
  def select_test_to_load(self, short_serial):
    # Load select_test_dialog
    tests_by_descrip = {}
    for test in self._tests[short_serial]:
      tests_by_descrip[self._test_descripts_by_file[test]] = test
    
    descrips = dict.keys(tests_by_descrip)
    descrips.sort()
    
    msg = 'Select component or component type to qualify.'

    choice = self.select_string_from_list(msg, descrips)
    if choice is None:
      return None
    return tests_by_descrip[choice]

  def on_char(self, event):
    # 347 is the keycode sent at the beginning of a barcode
    if (event.GetKeyCode() == 347):
      # Clear the old contents and put focus in the serial box so the rest of input goes there
      self._serial_text.Clear()
      self._serial_text_conf.Clear()

class ComponentQualFrame(QualificationFrame):
  def __init__(self, parent):
    QualificationFrame.__init__(self, parent)
    
    self.load_wg_test_map()
    self.create_menubar()

  def get_loader_panel(self):
    return SerialPanel(self._top_panel, self._res, self)
  
  ## TODO Overloaded in subclasses
  def create_menubar(self):
    menubar = wx.MenuBar()
    self._file_menu = wx.Menu()
    self._file_menu.Append(1001, "Invent Login\tCTRL+l")
    self._file_menu.Append(wx.ID_EXIT, "E&xit")
    menubar.Append(self._file_menu, "&File")

    self._options_menu = wx.Menu()
    self._options_menu.AppendCheckItem(2001, "Always Show Results")
    menubar.Append(self._options_menu, "&Options")

    self._powerboard_menu = wx.Menu()
    self._powerboard_menu.Append(3101, "Power Board\tCTRL+b")
    self._powerboard_menu.AppendCheckItem(3150, "Breaker 0\tCTRL+0")
    self._powerboard_menu.AppendCheckItem(3151, "Breaker 1\tCTRL+1")
    self._powerboard_menu.AppendCheckItem(3152, "Breaker 2\tCTRL+2")
    self._powerboard_menu.Check(3150, rospy.get_param('/qualification/powerboard/0'))
    self._powerboard_menu.Check(3151, rospy.get_param('/qualification/powerboard/1'))
    self._powerboard_menu.Check(3152, rospy.get_param('/qualification/powerboard/2'))

    menubar.Append(self._powerboard_menu, "&Powerboard")

    self._host_menu = wx.Menu()
    self._host_menu.Append(4001, "Select Test Host\tCTRL+h")
    menubar.Append(self._host_menu, "Test &Host")

    self.SetMenuBar(menubar)
    self.Bind(wx.EVT_MENU, self.on_menu)

  def get_powerboard(self):
    while not rospy.is_shutdown():
      # Get powerboard from user
      serial = wx.GetTextFromUser('Enter last four digits of power board serial number', 'Select Power Board', rospy.get_param('/qualification/powerboard/serial', ''))
      if len(serial) == 0:
        return
      if len(serial) == 4 and unicode(serial).isnumeric():
        rospy.set_param('/qualification/powerboard/serial', serial)
        return
      are_you_sure = wx.MessageDialog(self, 'Invalid powerboard ID. Retry?', 'Invalid serial',
                                      wx.OK|wx.CANCEL)
      if are_you_sure.ShowModal() != wx.ID_OK:
        return

  def on_menu(self, event):
    if (event.GetEventObject() == self._file_menu):
      if (event.GetId() == wx.ID_EXIT):
        self.Close()
        return
      if (event.GetId() == 1001):
        self.login_to_invent()
        return

    if (event.GetEventObject() == self._options_menu):
      if (event.GetId() == 2001):
        self._show_results_always = self._options_menu.IsChecked(2001)

    if (event.GetEventObject() == self._powerboard_menu):
      if (event.GetId() == 3101):
        self.get_powerboard()
      
      if (event.GetId() == 3150):
        rospy.set_param('/qualification/powerboard/0', self._powerboard_menu.IsChecked(3150))
      if (event.GetId() == 3151):
        rospy.set_param('/qualification/powerboard/1', self._powerboard_menu.IsChecked(3151))
      if (event.GetId() == 3152):
        rospy.set_param('/qualification/powerboard/2', self._powerboard_menu.IsChecked(3152))

    if (event.GetEventObject() == self._host_menu):
      if (event.GetId() == 4001):
        host = wx.GetTextFromUser('Enter test host', 'Test Host', os.environ['ROS_TEST_HOST'])
        os.environ['ROS_TEST_HOST'] = host


  ## TODO Only in component subclass
  def load_wg_test_map(self):
    # Load 'Map' of WG test locations to find defaults for this machine
    map_xml_path = os.path.join(roslib.packages.get_pkg_dir('qualification'), 'wg_map.xml')
    
    gui_name = socket.gethostname()

    try:
      doc = minidom.parse(map_xml_path)
    except IOError:
      rospy.logerr("Could not load test map from '%s'"%(map_xml_path))
      doc = None

    if doc:
      stations = doc.getElementsByTagName('station')
    
    # Sets default host, powerboard to None
    rospy.set_param('/qualification/powerboard/serial', '0000')
    rospy.set_param('/qualification/powerboard/0', False)
    rospy.set_param('/qualification/powerboard/1', False)
    rospy.set_param('/qualification/powerboard/2', False)
    os.environ['ROS_TEST_HOST'] = gui_name
    
    if not doc:
      wx.MessageBox('Error: Unable to parse \'qualification/wg_map.xml\'. Please check the document and retry.','Unable to parse configuration', wx.OK|wx.ICON_ERROR, self)

      return

    for station in stations:
      if station.attributes['gui'].value == gui_name:
        rospy.set_param('/qualification/powerboard/serial', station.attributes['powerboard'].value) 
        rospy.set_param('/qualification/powerboard/0', bool(station.attributes['breaker0'].value)) 
        rospy.set_param('/qualification/powerboard/1', bool(station.attributes['breaker1'].value)) 
        rospy.set_param('/qualification/powerboard/2', bool(station.attributes['breaker2'].value)) 
        os.environ['ROS_TEST_HOST'] = station.attributes['host'].value
        break
      
    if rospy.get_param('/qualification/powerboard/serial') == '0000':
      wx.MessageBox('Warning: Host %s not found in list of known hosts. Check file: \'qualification/wg_map.xml\' and retry.' % gui_name,'Host not found', wx.OK|wx.ICON_ERROR, self)
      


## Starts roscore, qualification app for components
class QualificationApp(wx.App):
  def OnInit(self):
    try:
      self._core_launcher = roslaunch_caller.launch_core()
    except RLException, e:
      sys.stderr.write('Failed to launch core. Another core may already be running.\n\n')
      sys.exit(0)
    except Exception, e:
      import traceback
      traceback.print_exc()
      sys.exit(0)
      
    rospy.init_node("qualification")
    
    self._frame = ComponentQualFrame(None)
    self._frame.SetSize(wx.Size(700,1000))
    self._frame.Layout()
    self._frame.Centre()
    self._frame.Show(True)
    
    return True

  def OnExit(self):
    self._core_launcher.stop()

