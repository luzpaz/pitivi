# -*- coding: utf-8 -*-
#
# Copyright (c) 2015, Thibault Saunier <tsaunier@gnome.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.
"""
A collection of objects to use for testing
"""
import gc
import os
import tempfile
import unittest
from unittest import mock

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import Gtk

from pitivi import check
from pitivi.application import Pitivi
from pitivi.utils.loggable import Loggable
from pitivi.utils.proxy import ProxyingStrategy
from pitivi.utils.proxy import ProxyManager
from pitivi.utils.timeline import Selected
from pitivi.utils.validate import Event

detect_leaks = os.environ.get("PITIVI_TEST_DETECT_LEAKS", "0") not in ("0", "")
os.environ["PITIVI_USER_CACHE_DIR"] = tempfile.mkdtemp("pitiviTestsuite")


def clean_pitivi_mock(app):
    app.settings = None
    app.proxy_manager = None


def create_pitivi_mock(proxyingStrategy=ProxyingStrategy.NOTHING,
                       numTranscodingJobs=4,
                       **additional_settings):

    def __create_settings():
        settings = mock.MagicMock()
        settings.proxyingStrategy = proxyingStrategy
        settings.numTranscodingJobs = numTranscodingJobs
        for key, value in additional_settings.items():
            setattr(settings, key, value)
        return settings

    app = mock.MagicMock()

    app.write_action = mock.MagicMock(spec=Pitivi.write_action)
    check.check_requirements()

    app.settings = __create_settings()
    app.proxy_manager = ProxyManager(app)

    return app


def create_main_loop():
    mainloop = GLib.MainLoop()
    timed_out = False

    def quit_cb(unused):
        timed_out = True
        mainloop.quit()

    def run(timeout_seconds=5):
        source = GLib.timeout_source_new_seconds(timeout_seconds)
        source.set_callback(quit_cb)
        source.attach()
        GLib.MainLoop.run(mainloop)
        source.destroy()
        if timed_out:
            raise Exception("Timed out after %s seconds" % timeout_seconds)

    mainloop.run = run
    return mainloop


class TestCase(unittest.TestCase, Loggable):
    _tracked_types = (Gst.MiniObject, Gst.Element, Gst.Pad, Gst.Caps)

    def __init__(self, *args):
        Loggable.__init__(self)
        unittest.TestCase.__init__(self, *args)

    def gctrack(self):
        self.gccollect()
        self._tracked = []
        for obj in gc.get_objects():
            if not isinstance(obj, self._tracked_types):
                continue

            self._tracked.append(obj)

    def gccollect(self):
        ret = 0
        while True:
            c = gc.collect()
            ret += c
            if c == 0:
                break
        return ret

    def gcverify(self):
        leaked = []
        for obj in gc.get_objects():
            if not isinstance(obj, self._tracked_types) or \
                    obj in self._tracked:
                continue

            leaked.append(obj)

        # we collect again here to get rid of temporary objects created in the
        # above loop
        self.gccollect()

        for elt in leaked:
            print(elt)
            for i in gc.get_referrers(elt):
                print("   ", i)

        self.assertFalse(leaked, leaked)
        del self._tracked

    def setUp(self):
        self._num_failures = len(getattr(self._result, 'failures', []))
        self._num_errors = len(getattr(self._result, 'errors', []))
        if detect_leaks:
            self.gctrack()

    def tearDown(self):
        # don't barf gc info all over the console if we have already failed a
        # test case
        if (self._num_failures < len(getattr(self._result, 'failures', [])) or
                self._num_errors < len(getattr(self._result, 'failures', []))):
            return
        if detect_leaks:
            self.gccollect()
            self.gcverify()

    # override run() to save a reference to the test result object
    def run(self, result=None):
        if not result:
            result = self.defaultTestResult()
        self._result = result
        unittest.TestCase.run(self, result)

    def toggleClipSelection(self, ges_clip, expect_selected):
        '''
        Toggle selection state of @ges_clip.
        '''
        selected = bool(ges_clip.ui.get_state_flags() & Gtk.StateFlags.SELECTED)
        self.assertEqual(ges_clip.selected.selected, selected)

        ges_clip.ui.sendFakeEvent(
            Event(Gdk.EventType.BUTTON_PRESS, button=1), ges_clip.ui)
        ges_clip.ui.sendFakeEvent(
            Event(Gdk.EventType.BUTTON_RELEASE, button=1), ges_clip.ui)

        self.assertEqual(bool(ges_clip.ui.get_state_flags() & Gtk.StateFlags.SELECTED),
                         expect_selected)
        self.assertEqual(ges_clip.selected.selected, expect_selected)

    def createTempProject(self):
        """
        Created a temporary project

        Always generate projects with missing assets for now

        Returns:
            str: The path of the new project
            str: The URI of the new project
        """
        unused_fd, xges_path = tempfile.mkstemp()
        with open(xges_path, "w") as xges:
            xges.write("""
<ges version='0.1'>
  <project>
    <ressources>
      <asset id='file:///icantpossiblyexist.png'
            extractable-type-name='GESUriClip' />
    </ressources>
    <timeline>
      <track caps='video/x-raw' track-type='4' track-id='0' />
      <layer priority='0'>
        <clip id='0' asset-id='file:///icantpossiblyexist.png'
            type-name='GESUriClip' layer-priority='0' track-types='4'
            start='0' duration='2590000000' inpoint='0' rate='0' />
      </layer>
    </timeline>
</project>
</ges>""")

        return xges_path, Gst.filename_to_uri(xges_path)


def getSampleUri(sample):
    assets_dir = os.path.dirname(os.path.abspath(__file__))

    return "file://%s" % os.path.join(assets_dir, "samples", sample)


def cleanProxySamples():
    _dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
    proxy_manager = ProxyManager(mock.MagicMock())

    for f in os.listdir(_dir):
        if f.endswith(proxy_manager.proxy_extension):
            f = os.path.join(_dir, f)
            os.remove(f)


class SignalMonitor(object):

    def __init__(self, obj, *signals):
        self.signals = signals
        self.connectToObj(obj)

    def connectToObj(self, obj):
        self.obj = obj
        for signal in self.signals:
            obj.connect(signal, self._signalCb, signal)
            setattr(self, self._getSignalCounterName(signal), 0)
            setattr(self, self._getSignalCollectName(signal), [])

    def disconnectFromObj(self, obj):
        obj.disconnect_by_func(self._signalCb)
        del self.obj

    def _getSignalCounterName(self, signal):
        field = '%s_count' % signal.replace('-', '_')
        return field

    def _getSignalCollectName(self, signal):
        field = '%s_collect' % signal.replace('-', '_')
        return field

    def _signalCb(self, obj, *args):
        name = args[-1]
        field = self._getSignalCounterName(name)
        setattr(self, field, getattr(self, field, 0) + 1)
        field = self._getSignalCollectName(name)
        setattr(self, field, getattr(self, field, []) + [args[:-1]])


def createTestClip(clip_type):
    clip = clip_type()
    clip.selected = Selected()

    return clip
