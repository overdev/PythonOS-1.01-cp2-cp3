# -*- coding: utf-8 -*-

"""
Created on Dec 27, 2015

@author: Adam Furman
@copyright: MIT License
"""


# NOTE: changed in 1.01 - using the print() function
from __future__ import print_function
# NOTE: new in 1.01 - import the sys module
import sys
import pygame
import json
import os
import apps
from types import ModuleType
from importlib import import_module
from zipfile import ZipFile
from shutil import rmtree
from traceback import format_exc
from copy import deepcopy
from collections import namedtuple
from collections import OrderedDict
from datetime import datetime
import ast

try:
    import pygame.freetype
    has_ft = True
except ImportError:
    has_ft = False
    pygame.freetype = None

major, minor, micro, rl, sr = sys.version_info

if major == 2:
    from thread import start_new_thread
    import __builtin__
    from __builtin__ import staticmethod

else:
    unicode = str
    raw_input = input
    __builtin__ = globals()['__builtins__']
    from threading import _start_new_thread as start_new_thread

COMMON_EXCEPTIONS = (ArithmeticError, AttributeError, BufferError, EOFError, LookupError, NameError, OSError,
                     RuntimeError, TypeError, ValueError)
# state = None
screen = None

DEFAULT = 0xada
DIR = os.path.split(__file__)[0]

# NOTE: New on 1.01 - Replace broad exception clauses by common expcetions and avoid KeyboardInterrupt


def read_file(path):
    # type: (str) -> list
    """Loads a text file from ``path`` into a list of str and returns it.
    """
    with open(path, "rU") as text:
        return text.readlines()


def read_json(path, default=None):
    # type: (str, Any) -> dict
    """Loads a JSON file into a dictionary and returns it or a default object on error.
    :param path: the file path to load from.
    :param default: the default value to return in case of error.
    """
    try:
        # with open(path, "rU") as f:
            # data = str(" ".join(f.readlines()))
            # print("JSON : [{}]\n{}\n--------------\n".format(path, data))
            # jsd = json.loads(data)
        # return jsd
        return SubData.load(os.path.normpath(os.path.join(DIR, path)))
    except COMMON_EXCEPTIONS:
        print(path)
        raise
    return default


class SubData(object):

    _indent = 0

    @classmethod
    def load(cls, fname):
        # type: (str) -> SubData
        print("subdata loading {}".format(fname))
        with open(fname) as sd:
            code = "".join(sd.readlines())
            subdat = ast.literal_eval(code)
        return cls(**subdat)

    @classmethod
    def items(cls, sd):
        # type: (SubData) -> tuple
        assert sd.__class__ is cls, "'sd' is not a SubData object."
        return sd._dict.items()

    @classmethod
    def values(cls, sd):
        # type: (SubData) -> tuple
        assert sd.__class__ is cls, "'sd' is not a SubData object."
        return sd._dict.values()

    def __init__(self, **kwargs):
        self._dict = OrderedDict()
        for key in kwargs:
            value = kwargs[key]
            if isinstance(value, (dict, OrderedDict)):
                self[key] = SubData(**value)
            else:
                setattr(self, key, value)

    def __getattr__(self, name):
        if name != '_dict':
            if name in getattr(self, '_dict'):
                return getattr(self, '_dict')[name]
            else:
                raise AttributeError("Subdata object has no '{}' attribute.".format(name))
        else:
            return self._dict

    def __setattr__(self, name, value):
        if name != '_dict':
            if isinstance(value, (dict, OrderedDict)):
                getattr(self, '_dict')[name] = SubData(**value)
            else:
                getattr(self, '_dict')[name] = value
        else:
            getattr(self, '__dict__')[name] = value

    def __delattr__(self, name):
        if name == '_dict':
            raise AttributeError("Could not delete the attribute.")
        else:
            if name in getattr(self, '_dict'):
                del getattr(self, '_dict')[name]
            else:
                raise AttributeError("Subdata object has no '{}' attribute.".format(name))

    def __str__(self):
        SubData._indent += 1
        indents = " " * (SubData._indent * 4)
        _items = ""
        for key in self._dict:
            _items += "{}'{}': {},\n".format(indents, key, repr(self._dict[key]))
        SubData._indent -= 1
        return "{{\n{}{}}}".format(_items, ' ' * (SubData._indent * 4))

    __repr__ = __str__

    def __getitem__(self, key):
        return self._dict.__getitem__(key)

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            self._dict.__setitem__(key, SubData(**value))
        else:
            self._dict.__setitem__(key, value)

    def __delitem__(self, key):
        self._dict.__delitem__(key)

    def __len__(self):
        return self._dict.__len__()

    def __iter__(self):
        return self._dict.__iter__()

    def __contains__(self, name):
        return name in self._dict

    def get(self, name, default=None):
        return self._dict.get(name, default)

    def copy(self):
        return SubData(**self._dict)

# NOTE: New on 1.01 - A namedtuple enumerating the thread pausing operations.
TaskPauseState = namedtuple("TaskPauseState", "false true toggle".split())(0, 1, 2)

# NOTE: New on 1.01 - A namedtuple enumerating the thread event types.
ThrEvt = namedtuple("ThrEvt", "on_start on_stop on_pause on_resume on_custom".split())(
    "onStart", "onStop", "onPause", "onResume", "onCustom")


class Thread(object):
    """Represents an OS thread.

    Serves as base for ``Task``, ``StagedTask``, ``TimedTask`` and ``ParallelTask``.
    """

    def __init__(self, method, **data):
        # type: (Callable, ...) -> None
        """Default instance construction initializer.
        :param method: the thread action to perform.
        :param data: the event related data.
        """
        self.event_bindings = {
            ThrEvt.on_start: None,
            ThrEvt.on_stop: None,
            ThrEvt.on_pause: None,
            ThrEvt.on_resume: None,
            ThrEvt.on_custom: None
        }  # type: dict
        self.pause = data.get("startPaused", False)  # type: bool
        self.stop = False  # type: bool
        self.first_run = True  # type: bool
        self.method = method  # type: callable
        self.event_bindings.update(data)

    @staticmethod
    def _default_evt_method(self, *args):
        # type: (...) -> None
        """Placeholder callback for task event handling. Does nothing.
        """
        return

    def exec_event(self, evt_key, *params):
        # type: (str, ...) -> None
        """Executes a thread event.

        :param evt_key: the event name to execute.
        :param params: the event arguments
        :return: None
        """
        to_exec = self.event_bindings.get(evt_key, Thread._default_evt_method)
        if to_exec is None:
            return
        if isinstance(to_exec, (list, tuple)):
            to_exec[0](*to_exec[1])
        else:
            to_exec(*params)

    def set_pause(self, pause_state=TaskPauseState.toggle):
        # type: (int) -> None
        """Pauses, resumes or toggles the execution of this thread.
        :param pause_state: the thread state to set.
        """
        if isinstance(pause_state, bool):
            self.pause = TaskPauseState[int(pause_state)]
        elif pause_state in TaskPauseState:
            if pause_state == TaskPauseState.toggle:
                if self.pause == TaskPauseState.true:
                    self.pause = TaskPauseState.false
                else:
                    self.pause = TaskPauseState.true
            else:
                self.pause = pause_state

        if self.pause == TaskPauseState.true:
            self.exec_event(ThrEvt.on_pause)
        else:
            self.exec_event(ThrEvt.on_resume)

    def set_stop(self):
        # type: () -> None
        """Stop this thread.
        :return: None
        """
        self.stop = True
        self.exec_event(ThrEvt.on_stop)

    def run(self):
        # type: () -> None
        """Executes this thread.
        :return: None
        """
        try:
            if self.first_run:
                if self.event_bindings[ThrEvt.on_start] is None:
                    self.exec_event(ThrEvt.on_start)
                self.first_run = False
            if not self.pause and not self.stop:
                self.method()
        # TODO: add more exceptions.
        except COMMON_EXCEPTIONS:
            State.error_recovery("Thread error.", "Thread bindings: " + str(self.event_bindings))
            self.stop = True
            self.first_run = False


class Task(Thread):
    """Represents an OS task.

    Tasks executes once, then terminate.
    """

    def __init__(self, method, *additional_data):
        # type: (callable, ...) -> None
        """Task instance constructor initializer.
        :param method: the task to execute.
        :param additional_data: data related to the task. Optional.
        """
        super(Task, self).__init__(method)
        self.returned_data = None  # type: Any
        self.additional_data = additional_data  # type: tuple

    def run(self):
        # type: () -> None
        """Runs this task.
        :return: None
        """
        self.returned_data = self.method(*self.additional_data)
        self.set_stop()

    def get_return(self):
        """Returns this task execution result, if any.
        :return: Any object.
        """
        return self.returned_data

    def set_pause(self, pause_state=TaskPauseState.toggle):
        """This method is not relevant for this class.
        :param pause_state: argument is not used.
        :return: None.
        """
        return

    def exec_event(self, evt_key, *params):
        """This method is not relevant for this class.
        :param evt_key: argument is not used.
        :param params: argument is not used.
        :return: None
        """
        return


class StagedTask(Task):
    """Represents a task that executes in a user-defined number of steps (or stages).
    """

    def __init__(self, method, max_stage=10):
        # type: (callable, int) -> None
        """StagedTask instance constructor initializer.
        :param method: the callback method to be executed.
        :param max_stage: the number of steps this task will perform.
        """
        super(StagedTask, self).__init__(method)
        self.stage = 1  # type: int
        self.max_stage = max_stage  # type: int

    def run(self):
        # type: () -> None
        """Run this task.
        :return: None.
        """
        self.returned_data = self.method(self.stage)
        self.stage += 1
        if self.stage >= self.max_stage:
            self.set_stop()


class TimedTask(Task):
    """Represents a task the executes after a time interval.
    """

    def __init__(self, execute_on, method, *additional_data):
        # type: (time, callable, ...) -> None
        self.execution_time = execute_on
        super(TimedTask, self).__init__(method, *additional_data)

    def run(self):
        # type: () -> None
        """Run this task.
        :return: None.
        """
        delta = self.execution_time - datetime.now()
        if delta.total_seconds() <= 0:
            super(TimedTask, self).run()


class ParallelTask(Task):
    """Represents a python thread.

    Warning: This starts a new thread.
    """

    def __init__(self, method, *additional_data):
        """ParallelTask instance initializer.
        :param method: the task to perform.
        :param additional_data: data related to the task. Optional.
        """
        super(ParallelTask, self).__init__(method, *additional_data)
        self.ran = False  # type: bool

    def run(self):
        # type: () -> None
        """Run this task.
        :return: None.
        """
        if not self.ran:
            start_new_thread(self.run_helper, ())
            self.ran = True

    def get_return(self):
        return None

    def run_helper(self):
        # type: () -> None
        """Task execution helper.
        :return: None.
        """
        self.method(*self.additional_data)
        self.set_stop()

    def set_stop(self):
        # type: () -> None
        """Stop this task.
        :return: None.
        """
        super(ParallelTask, self).set_stop()


class Controller(object):
    """Represents a thread/task controller.
    """

    def __init__(self):
        # type: () -> None
        """Controller instance initializer.
        """
        self.threads = []
        self.data_requests = {}

    def request_data(self, from_thread, default=None):
        # type: (str, Any) -> None
        """Sends a thread or task data request.
        :param from_thread: the thread key to request from.
        :param default: the default value.
        :return: None
        """
        self.data_requests[from_thread] = default

    def get_requested_data(self, from_thread):
        # type: (str) -> Any
        """Returns the requested data.
        :param from_thread:
        :return: the requested data
        """
        return self.data_requests[from_thread]

    def add_thread(self, thread):
        # type: (Thread) -> None
        """Adds a new Thread or Task.
        :param thread: the thread or task to add.
        :return: None.
        """
        self.threads.append(thread)

    def remove_thread(self, thread):
        # type: (Thread) -> None
        """Tries to remove the given thread.
        :param thread: the thread instance to remove or its index.
        :return: None.
        """
        try:
            if isinstance(thread, int):
                self.threads.pop(thread)
            else:
                self.threads.remove(thread)
        except COMMON_EXCEPTIONS:
            print("Thread was not removed!")

    def stop_all_threads(self):
        # type: () -> None
        """Interrupts the execution of all currently active threads.
        :return: None.
        """
        for thread in self.threads:
            thread.set_stop()

    def run(self):
        # type: () -> None
        """Runs this controller and all of its threads and tasks.
        :return: None.
        """
        for thread in self.threads:
            thread.run()
            if thread in self.data_requests:
                try:
                    self.data_requests[thread] = thread.getReturn()
                except COMMON_EXCEPTIONS:
                    self.data_requests[thread] = False  # getReturn called on Thread, not Task
            if thread.stop:
                self.threads.remove(thread)

# NOTE: new in 1.01 - A namedtuple enumerating checkbox states.
CheckboxState = namedtuple("CheckboxState", "unchecked checked toggle".split())(0, 1, 2)

# NOTE: new in 1.01 - A namedtuple enumerating switch states.
SwitchState = namedtuple("SwitchState", "off on toggle".split())(0, 1, 2)


class GUI(object):
    """Represents the Graphical User Interface toolkit.
    """

    # NOTE: new in 1.01 - added the DEFAULT_RESOLUTION class constant
    DEFAULT_RESOLUTION = {"width": 240, "height": 320}

    def __init__(self):
        # type: () -> None
        """GUI instance initializer.
        """
        global screen
        self.orientation = 0  # 0 for portrait, 1 for landscape
        self.timer = None
        self.update_interval = 30
        pygame.init()
        if __import__("sys").platform == "linux2" and os.path.isdir("/home/pi"):
            pygame.mouse.set_visible(False)
            info = pygame.display.Info()
            self.width = info.current_w
            self.height = info.current_h
            screen = pygame.display.set_mode((info.current_w, info.current_h))
        else:
            scrdat = read_json("res/settings.json", {})
            screen_size = scrdat.get("scren_size", self.DEFAULT_RESOLUTION)
            screen = pygame.display.set_mode(
                (int(screen_size.get("width")), int(screen_size.get("height"))), pygame.HWACCEL)
            self.width = screen.get_width()
            self.height = screen.get_height()
        try:
            screen.blit(pygame.image.load("res/splash2.png"), [0, 0])
        except COMMON_EXCEPTIONS:
            screen.blit(pygame.font.Font(None, 20).render("Loading Python OS 6...", 1, (200, 200, 200)), [5, 5])
        pygame.display.flip()
        __builtin__.screen = screen
        globals()["screen"] = screen
        self.timer = pygame.time.Clock()
        pygame.display.set_caption("PyOS 6")

    def orient(self):
        # type: () -> None
        """Updates screen orientation.
        :return: None
        """
        global screen
        self.orientation = 0 if self.orientation == 1 else 1
        bk = self.width
        self.width = self.height
        self.height = bk
        screen = pygame.display.set_mode((self.width, self.height))
        for app in state.application_list.application_list:
            app.ui.refresh()
        State.rescue()

    def repaint(self):
        # type: () -> None
        """Clears the screen to the background color.
        :return: None.
        """
        screen.fill(state.color_palette.get_color(GUI.Palette.background))

    def refresh(self):
        # type: () -> None
        """Updates the display.
        :return: None.
        """
        pygame.display.flip()

    # NOTE: New in 1.01 - getScreen turned into a property
    @property
    def screen(self):
        # type: () -> pygame.Surface
        """Gets the display surface.
        """
        return screen

    def monitor_fps(self):
        # type: () -> None
        """Updates the screen refresh rate.
        """
        real = round(self.timer.get_fps())
        if real >= self.update_interval and self.update_interval < 30:
            self.update_interval += 1
        else:
            if self.update_interval > 10:
                self.update_interval -= 1

    # NOTE: New in 1.01 - display_standby_text() turned into a staticmethod.
    @staticmethod
    def display_standby_text(text="Stand by...", size=20, color=(20, 20, 20), bgcolor=(100, 100, 200)):
        # type: (str, int, tuple, tuple) -> None
        """Renders a small box with a text message.
        """
        pygame.draw.rect(screen, bgcolor,
                         [0, ((state.gui.height - 40) / 2) - size, state.gui.width, 2 * size])
        screen.blit(state.font.get(size).render(text, 1, color),
                    (5, ((state.gui.height - 40) / 2) - size + (size / 4)))
        pygame.display.flip()

    @staticmethod
    def get_centered_coordinates(component, larger):
        # type: (Component, Component) -> list
        """Centers a component inside its container boundaries.
        :param component: the component to centralize.
        :param larger: the container to align into.
        :return: a 2-int list (a position)
        """
        return [(larger.computed_width / 2) - (component.computed_width / 2),
                (larger.computed_height / 2) - (component.computed_height / 2)]

    class Font(object):
        """Encapsulates the pygame Font class.
        """

        def __init__(self, path="res/RobotoCondensed-Regular.ttf", min_size=10, max_size=30):
            # type: (str, int, int) -> None
            """Font instance initializer.
            :param path: the source TrueType font to use.
            :param min_size: the minimum font size.
            :param max_size: the maximum font size.
            """
            self.path = path  # type: str
            self.sizes = {}  # type: dict
            self.ft_sizes = {}  # type: dict
            curr_size = min_size  # type: int

            self.freetype = None
            if has_ft:
                self.freetype = pygame.freetype

            while curr_size <= max_size:
                if self.freetype is not None:
                    self.ft_sizes[curr_size] = self.freetype.Font(path, curr_size)
                self.sizes[curr_size] = pygame.font.Font(path, curr_size)
                curr_size += 1

        def get(self, size=14, ft=False):
            # type: (int, bool) -> Union[pygame.Font, freetype.Font]
            """Returns the Font object used for rendering.
            :param size: the font size.
            :param ft: True if the font object is a freetype.Font, False if it is a pygame.Font
            """
            if ft:
                if size not in self.ft_sizes:
                    self.ft_sizes[size] = self.freetype.Font(self.path, size)
                return self.ft_sizes[size]
            else:
                if size not in self.sizes:
                    self.sizes[size] = pygame.font.Font(self.path, size)
                return self.sizes[size]

    class Icons(object):
        """Represents the icon library.
        """

        def __init__(self):
            # type: () -> None
            """Icons instance initializer.
            """
            self._root_path = "res/icons/"  # type: str
            self._icons = {
                "menu": "menu.png",
                "unknown": "unknown.png",
                "error": "error.png",
                "warning": "warning.png",
                "file": "file.png",
                "folder": "folder.png",
                "wifi": "wifi.png",
                "python": "python.png",
                "quit": "quit.png",
                "copy": "files_copy.png",
                "delete": "files_delete.png",
                "goto": "files_goto.png",
                "home_dir": "files_home.png",
                "move": "files_move.png",
                "select": "files_select.png",
                "up": "files_up.png",
                "back": "back.png",
                "forward": "forward.png",
                "search": "search.png",
                "info": "info.png",
                "open": "open.png",
                "save": "save.png"
            }  # type: dict

        @property
        def icons(self):
            # type: () -> dict
            """Gets the icons dictionary."""
            return self._icons

        @property
        def root_path(self):
            return self._root_path

        def get_loaded_icon(self, icon, folder=""):
            # type: (str, str) -> pygame.Surface
            """Loads and returns an icon.
            """
            try:
                return pygame.image.load(os.path.join(self._root_path, self._icons[icon]))
            except pygame.error:
                if os.path.exists(icon):
                    return pygame.transform.scale(pygame.image.load(icon), (40, 40))
                if os.path.exists(os.path.join("res/icons/", icon)):
                    return pygame.transform.scale(pygame.image.load(os.path.join("res/icons/", icon)), (40, 40))
                if os.path.exists(os.path.join(folder, icon)):
                    return pygame.transform.scale(pygame.image.load(os.path.join(folder, icon)), (40, 40))
                return pygame.image.load(os.path.join(self._root_path, self._icons["unknown"]))

        @staticmethod
        def load_from_file(path):
            # type: (str) -> GUI.Icons
            """Loads the object data from a json file.
            """
            f = open(path, "rU")
            icondata = json.load(f)
            toreturn = GUI.Icons()
            for key in dict(icondata).keys():
                toreturn._icons[key] = icondata.get(key)
            f.close()
            return toreturn

    # NOTE: new in 1.01 - namedtuples enumerating palette elements and color schemes
    Palette = namedtuple("Palette", "background item accent warning error".split())(
        "background", "item", "accent", "warning", "error")
    Scheme = namedtuple("Scheme", "normal dark light")("normal", "dark", "light")

    # NOTE: new in 1.01 - named tuple enumerating color bright modifiers.
    ColorBrightness = namedtuple("Scheme", "normal darkest darker dark light lighter lightest".split())(
        0., -0.75, -0.5, -0.25, 0.25, 0.5, 0.75)

    class ColorPalette(object):
        def __init__(self):
            self._palette = {
                GUI.Scheme.normal: {
                    GUI.Palette.background: (200, 200, 200),
                    GUI.Palette.item: (20, 20, 20),
                    GUI.Palette.accent: (100, 100, 200),
                    GUI.Palette.warning: (250, 160, 45),
                    GUI.Palette.error: (250, 50, 50)
                },
                GUI.Scheme.dark: {
                    GUI.Palette.background: (50, 50, 50),
                    GUI.Palette.item: (220, 220, 220),
                    GUI.Palette.accent: (50, 50, 150),
                    GUI.Palette.warning: (200, 110, 0),
                    GUI.Palette.error: (200, 0, 0)
                },
                GUI.Scheme.light: {
                    GUI.Palette.background: (250, 250, 250),
                    GUI.Palette.item: (50, 50, 50),
                    GUI.Palette.accent: (150, 150, 250),
                    GUI.Palette.warning: (250, 210, 95),
                    GUI.Palette.error: (250, 100, 100)
                }
            }  # type: dict
            self._scheme = GUI.Scheme.normal  # type: str

        # NOTE: New in 1.01 - getPalette() turned into a property
        @property
        def palette(self):
            # type: () -> dict
            return self._palette

        # NOTE: New in 1.01 - getScheme and setScheme() turned into a property
        @property
        def scheme(self):
            # type: () -> str
            """Gets or sets the current color scheme
            """
            return self._scheme

        @scheme.setter
        def scheme(self, value):
            # type: (str) -> None
            self._scheme = value

        # NOTE: new in 1.01 - new get_color() algorithm with enhanced functionality
        def get_color(self, item, brightness=None):
            # type: (str, Union[int, float]) -> tuple
            """Returns a color from the color scheme. Use brightness to add or reduce the
            color. If an int is provided, value must pass in the -255 <= brigh <= 255 test for the change
            to be applied; for a float, value must pass in the -1.0 <= bright <= 1.0 test as well.
            Unexpected brighness arguments will leave the color unmodified. Note that a brightness of 127
            will not return the same color as 0.5, the calculations are diferent.

            :param item: the palette color item name.
            :param brightness: the amount of brightness to add to or subtract from the color.
            :return: a 3-int RGB color.
            """
            color = self._palette[self._scheme][item]
            r, g, b = color

            if brightness is not None:

                if brightness == 0:
                    color = int(r), int(g), int(b)

                elif isinstance(brightness, int) and -255 <= brightness <= 255:
                    r = max(0, min(r + brightness, 255))
                    g = max(0, min(g + brightness, 255))
                    b = max(0, min(b + brightness, 255))

                    return r, g, b

                elif isinstance(brightness, float) and -1. <= brightness <= 1.:
                    if brightness < 0:
                        r1 = g1 = b1 = 0
                    else:
                        r1 = g1 = b1 = 255

                    r = int(r + (r1 - r) * abs(brightness))
                    g = int(g + (g1 - g) * abs(brightness))
                    b = int(b + (b1 - b) * abs(brightness))

                    return r, g, b

                else:
                    return color
            return int(r), int(g), int(b)

        def get_color2(self, item):
            if item.find(":") == -1:
                return self._palette[self._scheme][item]
            else:
                split = item.split(":")
                cadd = lambda c, d: (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if split[0] == "darker":
                    return max(cadd(self.get_color(split[1]), (-20, -20, -20)), (0, 0, 0))
                if split[0] == "dark":
                    return max(cadd(self.get_color(split[1]), (-40, -40, -40)), (0, 0, 0))
                if split[0] == "lighter":
                    return min(cadd(self.get_color(split[1]), (20, 20, 20)), (250, 250, 250))
                if split[0] == "light":
                    return min(cadd(self.get_color(split[1]), (40, 40, 40)), (250, 250, 250))
                if split[0] == "transparent":
                    return self.get_color(split[1]) + (int(split[2].rstrip("%")) / 100,)

        def __getitem__(self, item):
            # type: (str) -> tuple
            """Mapping emulation. Operates similarly with get_color()
            """
            return self.get_color(item)

        @staticmethod
        def load_from_file(path):
            # type: (str) -> GUI.ColorPalette
            """Loads a ColorPalette from a json file.
            """
            f = open(path, "rU")
            colordata = json.load(f)
            toreturn = GUI.ColorPalette()
            for key in dict(colordata).keys():
                toreturn._palette[key] = colordata.get(key)
            f.close()
            return toreturn

        @staticmethod
        def html_to_rgb(colorstring):
            # type: (str) -> Tuple[int, int, int]
            """Converts a web format rgb color (`#RRGGGBB`) into a 3-int tuple rgb color
            """
            colorstring = colorstring.strip().strip('#')
            if len(colorstring) != 6:
                raise ValueError("input #{} is not in #RRGGBB format".format(colorstring))

            elif False in map(lambda ch: ch.lower in '0123456789abcdef', colorstring):
                raise ValueError("invalid #RRGGBB format (unexpected character)")

            rgb = colorstring[:2], colorstring[2:4], colorstring[4:]
            return tuple(int(n, 16) for n in rgb)

        @staticmethod
        def rgb_to_html(rgb_tuple):
            # type: (Tuple[int, int, int]) -> str
            return '#{:02X}{:02X}{:02X}'.format(*rgb_tuple)

    # NOTE: new in 1.01 - Event base class for LongClickEvent and IntermediateUpdateEvent
    class Event(object):
        """Base class for LongClickEvent and IntermediateUpdateEvent events.

        It does nothing.
        """
        __slots__ = ()

    class LongClickEvent(Event):
        """Represents a long screen touch or mouse button press.
        """

        def __init__(self, mouse_down):
            # type: (pygame.event.Event) -> None
            """LongClickEvent instance initializer.
            :param mouse_down: the corresponding pygame.MOUSEBUTTONDOWN event instance.
            """
            self.mouse_down = mouse_down  # type: pygame.event.Event
            self.mouse_down_time = datetime.now()  # type: datetime.time
            self.mouse_up = None  # type: pygame.event.Event
            self.mouse_up_time = None  # type: datetime.time
            self.intermediate_points = []  # type: list
            self.pos = self.mouse_down.pos  # type: tuple

        def intermediate_update(self, mouse_move):
            # type: (pygame.event.Event) -> None
            """Captures and updates the mouse movement path during a long click event.
            :param mouse_move: the corresponding pygame.MOUSEMOTION event instance.
            """
            if self.mouse_up is None and (
                            len(self.intermediate_points) == 0 or mouse_move.pos != self.intermediate_points[-1]):
                self.intermediate_points.append(mouse_move.pos)

        def end(self, mouse_up):
            # type: (pygame.event.Event) -> None
            """Terminates the long click event processing.
            :param mouse_up: the corresponding pygame.MOUSEBUTTONUP event instance.
            """
            self.mouse_up = mouse_up
            self.mouse_up_time = datetime.now()
            self.pos = self.mouse_up.pos

        # NOTE: new in 1.01 - getLatestUpdate() turned into a property.
        @property
        def latest_update(self):
            # type: () -> Tuple[int, int]
            """Gets the last mouse position during the long click event.

            If there's not a position, the current position is returned.
            """
            if len(self.intermediate_points) == 0:
                return self.pos
            else:
                return self.intermediate_points[-1]

        def is_valid_longclick(self, time=300):
            # type: (int) -> bool
            """Checks timestamps against a time interval.
            :param time: the time interval in milliseconds.
            """
            delta = self.mouse_up_time - self.mouse_down_time
            return (delta.microseconds / 1000) >= time

    class IntermediateUpdateEvent(Event):
        """Represents?
        """
        # NOTE: new in 1.01 - __slots__ added, to reduce memory usage.
        __slots__ = 'pos', 'source_event'

        def __init__(self, pos, src):
            # type: Tuple[int, int], pygame.event.Event) -> None
            """IntermediateUpdateEvent instance initializer.
            :param pos: a mouse position.
            :param src: the source event.
            """
            self.pos = pos  # type: tuple
            self.source_event = src  # type: pygame.event.Event

    class EventQueue(object):
        """Represents a queue of events to be processed (or handled).
        """
        # NOTE: new in 1.01 - __slots__ added, to reduce memory usage.
        __slots__ = ('events',)

        def __init__(self):
            # type: () -> None
            """EventQueue instance initializer.
            """
            self.events = []  # type: list

        # NOTE: new in 1.01 - the empty property.
        @property
        def empty(self):
            # type: () -> bool
            """True if there is no events in the queue, False otherwise.
            """
            return len(self.events) == 0

        # NOTE: new in 1.01 - the tail property.
        @property
        def tail(self):
            # type: () -> Any
            """Gets or sets the last event of the queue (returns None if its empty).
            """
            if not self.empty:
                return self.events[-1]
            return None

        @tail.setter
        def tail(self, value):
            # type: (Any) -> None
            if not self.empty:
                self.events[-1] = value

        def check(self):
            # type: () -> None
            """Updates the event queue.
            """
            # for event in pygame.event.get():
            #     print(event.type == pygame.MOUSEBUTTONUP, self.tail.__class__.__name__)
            #
            #     last_event = None               # type: GUI.LongClickEvent
            #     if not self.empty and isinstance(self.tail, GUI.LongClickEvent):
            #         last_event = self.tail
            #
            #     if event.type == pygame.QUIT:
            #         State.exit()
            #
            #     elif event.type == pygame.MOUSEBUTTONUP and last_event is not None:
            #         print("MOUSE UP")
            #         last_event.end(event)
            #         if not last_event.is_valid_longclick():
            #             self.tail = last_event.mouse_up
            #
            #     elif event.type == pygame.MOUSEBUTTONDOWN:
            #         self.events.append(GUI.LongClickEvent(event))
            #
            #     elif event.type == pygame.MOUSEMOTION and last_event is not None:
            #         last_event.intermediate_update(event)
            for event in pygame.event.get():
                empty = len(self.events) == 0

                if event.type == pygame.QUIT:
                    State.exit()
                if event.type == pygame.MOUSEBUTTONDOWN:
                    self.events.append(GUI.LongClickEvent(event))

                if (event.type == pygame.MOUSEMOTION and not empty and
                        isinstance(self.events[-1], GUI.LongClickEvent)):
                    self.events[-1].intermediate_update(event)

                if (event.type == pygame.MOUSEBUTTONUP and not empty and
                        isinstance(self.events[-1], GUI.LongClickEvent)):
                    self.events[-1].end(event)
                    if not self.events[-1].check_valid_longclick():
                        self.events[-1] = self.events[-1].mouse_up

        def get_latest(self):
            # type: () -> GUI.Event
            """Removes and returns the last event of the queue.
            """
            if self.empty:
                return None
            return self.events.pop()

        def remove_event(self, ev):
            # type: (GUI.Event) -> None
            """Removes the given event from the queue.
            """
            if ev in self.events:
                self.events.remove(ev)

        @property
        def latest_complete(self):
            # type: () -> Event
            """Gets the last complete event from the queue or None if the queue is empty.

            The event returned is removed from the queue.
            """
            for event in reversed(self.events[:]):
                if isinstance(event, GUI.LongClickEvent):
                    if event.mouse_up is None:
                        self.events.remove(event)
                        return event
                    else:
                        return GUI.IntermediateUpdateEvent(self.tail.latest_update, self.tail)
                else:
                    self.events.remove(event)
                    return event
            return None

        def clear(self):
            # type: () -> None
            """Removes all events from the queue.
            """
            del self.events[:]  # remember to replace this by list.clear() in Python3

    # NOTE: New on 1.01 - A namedtuple enumerating the component event types.
    CompEvt = namedtuple(
        "CompEvt",
        "on_click on_longclick on_intermediate_updt".split()
    )("onClick", "onLongClick", "onIntermediateUpdate")

    # Note: new on 1.01 - A namedtuple enumerating the component event data.
    CompEvtData = namedtuple(
        "CompEvtData",
        "on_click_data on_longclick_data on_intermediate_updt_data".split()
    )("onClickData", "onLongClickData", "onIntermediateUpdateData")

    class Component(object):
        """Component is the base class of ui elements of the GUI toolkit.
        """

        def __init__(self, position, **data):
            # type: (Tuple[int, int], ...) -> None
            """Component instance initializer.
            :param position: the component position.
            :param data: optional set of keyword arguments related to the component.
            """
            self.position = list(deepcopy(position))
            self.event_bindings = {comp_evt: None for comp_evt in GUI.CompEvt}
            self.event_data = {evt_data: None for evt_data in GUI.CompEvtData}
            self.data = data
            self.surface = data.get("surface", None)
            self.border = 0
            self.border_color = (0, 0, 0)
            self.resizable = data.get("resizable", False)
            self.originals = [list(deepcopy(position)),
                              data.get("width",
                                       data["surface"].get_width() if data.get("surface", False) is not False else 0),
                              data.get("height",
                                       data["surface"].get_height() if data.get("surface", False) is not False else 0)
                              ]
            self.width = self.originals[1]
            self.height = self.originals[2]
            self.computed_width = 0
            self.computed_height = 0
            self.computed_position = [0, 0]
            self.rect = pygame.Rect(self.computed_position, (self.computed_width, self.computed_height))
            self._inner_click_coordinates = (-1, -1)
            self.inner_offset = [0, 0]
            self.internal_click_overrides = {}

            self.set_dimensions()

            for comp_evt in GUI.CompEvt:
                self.event_bindings[comp_evt] = data.get(comp_evt)

            for comp_data in GUI.CompEvtData:
                self.event_data[comp_data] = data.get(comp_data)

            if "border" in data:
                self.border = int(data["border"])
                self.border_color = data.get("borderColor", state.color_palette.get_color(GUI.Palette.background))

        def _percent_to_pix(self, value, scale):
            # type: (str, int) -> int
            """Converts a percentage value (as str) to a pixel value (as int).
            """
            return int(int(value.rstrip("%")) * scale)

        def set_dimensions(self):
            old_surface = self.surface.copy() if self.surface is not None else None  # type: pygame.Surface

            if self.data.get("fixedSize", False):
                self.computed_width = self.data.get("width")
                self.computed_height = self.data.get("height")
                self.rect = pygame.Rect(self.computed_position, (self.computed_width, self.computed_height))
                self.surface = pygame.Surface((self.computed_width, self.computed_height), pygame.SRCALPHA)
                if old_surface is not None:
                    self.surface.blit(old_surface, (0, 0))
                return
            appc = state.active_application.ui
            # Compute Position
            if isinstance(self.position[0], str):
                self.computed_position[0] = self._percent_to_pix(self.position[0],
                                                                 (state.active_application.ui.width / 100.0))
            else:
                if self.resizable:
                    self.computed_position[0] = int(self.position[0] * appc.scale_x)
                else:
                    self.computed_position[0] = int(self.position[0])

            if isinstance(self.position[1], str):
                self.computed_position[1] = self._percent_to_pix(self.position[1],
                                                                 (state.active_application.ui.height / 100.0))
            else:
                if self.resizable:
                    self.computed_position[1] = int(self.position[1] * appc.scale_y)
                else:
                    self.computed_position[1] = int(self.position[1])

            # Compute Width and Height
            if isinstance(self.width, str):
                self.computed_width = self._percent_to_pix(self.width, (state.active_application.ui.width / 100.0))
            else:
                if self.resizable:
                    self.computed_width = int(self.width * appc.scale_x)
                else:
                    self.computed_width = int(self.width)
            if isinstance(self.height, str):
                self.computed_height = self._percent_to_pix(
                    self.height, (state.active_application.ui.height / 100.0))
            else:
                if self.resizable:
                    self.computed_height = int(self.height * appc.scale_y)
                else:
                    self.computed_height = int(self.height)

            # print("Computed to: {}, {}x{}, {}".format(
            #     self.computed_position, self.computed_width, self.computed_height, self.resizable))

            self.rect = pygame.Rect(self.computed_position, (self.computed_width, self.computed_height))
            self.surface = pygame.Surface((self.computed_width, self.computed_height), pygame.SRCALPHA)

            if old_surface is not None:
                self.surface.blit(old_surface, (0, 0))

        # NOTE: new in 1.01 - the non public _handles() method.
        def _handles(self, event):
            # type: (str) -> bool
            """Returns whether the given event name is being handle by the component.
            """
            # could also check if `event` is a valid CompEvt member
            return event in self.event_bindings and self.event_bindings[event] is not None

        # NOTE: new in 1.01 - the non public _overrides() method.
        def _overrides(self, event):
            # type: (str) -> bool
            """Returns whether the given event name is being overriden by the component.
            """
            # could also check if `event` is a valid CompEvt member
            return event in self.internal_click_overrides and self.internal_click_overrides[event] is not None

        def _has_evtdata(self, event):
            # type: (str) -> bool
            """Returns whether the given event name is being overriden by the component.
            """
            # could also check if `event` is a valid CompEvtData member
            return event in self.event_data and self.event_data[event] is not None

        def on_click(self):
            # type: () -> None
            """Processes onClick event for this component.
            """
            print("onClick event:\n\t{}\n\t{}".format(self.__class__.__name__, self.data))
            on_click = GUI.CompEvt.on_click
            on_click_data = GUI.CompEvtData.on_click_data
            if self._overrides(on_click):
                self.internal_click_overrides[on_click][0](
                    *self.internal_click_overrides[on_click][1])

            if self._handles(on_click):
                if self._has_evtdata(on_click_data):
                    self.event_bindings[on_click](*self.event_data[on_click_data])
                else:
                    self.event_bindings[on_click]()

        def on_long_click(self):
            # type: () -> None
            """Processes onLongClick event for this component.
            """
            print("onClick event:\n\t{}\n\t{}".format(self.__class__.__name__, self.data))
            on_longclick = GUI.CompEvt.on_longclick
            on_longclick_data = GUI.CompEvtData.on_longclick_data
            if self._overrides(on_longclick):
                self.internal_click_overrides[on_longclick][0](
                    *self.internal_click_overrides[on_longclick][1])
            if self._handles(on_longclick):
                if self._has_evtdata(on_longclick_data):
                    self.event_bindings[on_longclick](*self.event_data[on_longclick_data])
                else:
                    self.event_bindings[on_longclick]()

        def on_intermediate_update(self):
            # type: () -> None
            """Processes onIntermediateUpdate event for this component.
            """
            on_intermediate_updt = GUI.CompEvt.on_intermediate_updt
            on_intermediate_updt_data = GUI.CompEvtData.on_intermediate_updt_data
            if self._overrides(on_intermediate_updt):
                self.internal_click_overrides[on_intermediate_updt][0](
                    *self.internal_click_overrides[on_intermediate_updt][1])

            if self._handles(on_intermediate_updt):
                if self._has_evtdata(on_intermediate_updt_data):
                    self.event_bindings[on_intermediate_updt](
                        *self.event_data[on_intermediate_updt_data])
                else:
                    self.event_bindings[on_intermediate_updt]()

        def set_on_click(self, mtd, data=()):
            # type: (callable, tuple) -> None
            """Registers the onClick event handler
            """
            self.event_bindings["onClick"] = mtd
            self.event_data["onClick"] = data

        def set_on_long_click(self, mtd, data=()):
            # type: (callable, tuple) -> None
            """Registers the onLongClick event handler
            """
            self.event_bindings["onLongClick"] = mtd
            self.event_data["onLong"] = data

        def set_on_intermediate_update(self, mtd, data=()):
            # type: (callable, tuple) -> None
            """Registers the onIntermediateUpdate event handler
            """
            self.event_bindings["onIntermediateUpdate"] = mtd
            self.event_data["onIntermediateUpdate"] = data

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the component.

            :param larger_surface: the surface to blit this component into.
            """
            recompute = False
            if self.position != self.originals[0]:
                self.originals[0] = list(deepcopy(self.position))
                recompute = True
            if self.width != self.originals[1]:
                self.originals[1] = self.width
                recompute = True
            if self.height != self.originals[2]:
                self.originals[2] = self.height
                recompute = True
            if recompute:
                self.set_dimensions()
            if self.border > 0:
                pygame.draw.rect(self.surface, self.border_color, [0, 0, self.computed_width, self.computed_height],
                                 self.border)
            if not self.surface.get_locked():
                larger_surface.blit(self.surface, self.computed_position)

        def refresh(self):
            # type: () -> None
            """Updates the component's boundaries.
            """
            self.set_dimensions()

        # NOTE: new in 1.01 - getInnerClickCoordinates() turned into a property
        @property
        def inner_click_coordinates(self):
            # type: () -> tuple
            """Gets a coordinate relative to the component's boundaries (client space)."""
            return self._inner_click_coordinates

        def check_click(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> bool
            """Updates the inner_click_coordinates and returns whether the event occurred inside bounds.
            :param mouse_event: the pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN ou pygame.MOUSEBUTTONUP instance.
            :param offset_x: non client left offset
            :param offset_y: non client top offset
            """
            self.inner_offset = [offset_x, offset_y]
            adjusted = [mouse_event.pos[0] - offset_x, mouse_event.pos[1] - offset_y]
            if adjusted[0] < 0 or adjusted[1] < 0:
                return False
            if self.rect.collidepoint(*adjusted):
                self._inner_click_coordinates = tuple(adjusted)
                if not isinstance(mouse_event, GUI.IntermediateUpdateEvent):
                    self.data["lastEvent"] = mouse_event
                return True
            return False

        def set_position(self, pos):
            # type: (Union[tuple, list]) -> None
            """Sets the component's position.

            Updates the component's dimentions.
            :param pos: the new position.
            """
            self.position = list(pos)
            self.refresh()

        def set_surface(self, new_surface, override_dimensions=False):
            # type: (pygame.Surface, bool) -> None
            """Sets the component surface, optionally overriding current dimentions (false by default).
            """
            if new_surface.get_width() != self.computed_width or new_surface.get_height() != self.computed_height:
                if override_dimensions:
                    self.width = new_surface.get_width()
                    self.height = new_surface.get_height()
                else:
                    new_surface = pygame.transform.scale(new_surface, (self.computed_width, self.computed_height))
            self.surface = new_surface

        @staticmethod
        def default(*items):
            # type: (...) -> tuple
            """Returns the component's defaults"""
            if len(items) % 2 != 0:
                return items
            values = []
            # index = 0
            for index in range(0, len(items), 2):
                values.append(items[index + 1] if items[index] == DEFAULT else items[index])
                # index += 2
            return tuple(values)

    class Container(Component):
        """Represents a Component that can contain other Components.
        """

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """Container instance initializer.
            :param position: the container position on screen.
            :param data: common data related to the component, such as color, back color and so on.
            """
            super(GUI.Container, self).__init__(position, **data)
            self.transparent = False
            self.background_color = (0, 0, 0)
            self.child_components = []
            self.SKIP_CHILD_CHECK = False
            self.transparent = data.get("transparent", False)  # type: bool
            self.background_color = data.get("color", state.color_palette.get_color(GUI.Palette.background))
            if "children" in data:
                self.child_components = data["children"]

        def add_child(self, component):
            # type: (Union[Component, Container]) -> None
            """Adds a child component.

            If the component is resizable, it will be resized to fit the container bounds.
            :param component: the child component to add.
            """
            if self.resizable and "resizable" not in component.data:
                component.resizable = True
                component.refresh()
            self.child_components.append(component)

        def add_children(self, *children):
            # type: (...) -> None
            """Adds a sequence of child components.
            """
            for child in children:
                self.add_child(child)

        def remove_child(self, component):
            # type: (Union[Component, Container]) -> None
            """Removes a child component.
            """
            self.child_components.remove(component)

        def clear_children(self):
            # type: (Union[Component, Container]) -> None
            """Removes all child components.
            """
            del self.child_components[:]

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> Component
            """Returns the component that contains the mouse event.
            :param mouse_event: the mouse event to check.
            :param offset_x: non client left offset
            :param offset_y: non client top offset
            :return: a component or None
            """
            for child in reversed(self.child_components[:]):
                # curr_child -= 1
                # child = self.child_components[curr_child]
                if hasattr(child, "SKIP_CHILD_CHECK"):
                    if child.SKIP_CHILD_CHECK:
                        if child.check_click(mouse_event, offset_x + self.computed_position[0],
                                             offset_y + self.computed_position[1]):
                            return child
                        else:
                            continue
                    else:
                        sub_check = child.get_clicked_child(mouse_event, offset_x + self.computed_position[0],
                                                            offset_y + self.computed_position[1])
                        if sub_check is None:
                            continue
                        return sub_check
                else:
                    if child.check_click(mouse_event, offset_x + self.computed_position[0],
                                         offset_y + self.computed_position[1]):
                        return child
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def get_child_at(self, position):
            # type: (Union[tuple, list]) -> Component
            """Returns a child component under the given position, if any, or None otherwise.
            :param position: the position to look up.
            :return: A component or None.
            """
            for child in self.child_components:
                if child.computed_position == list(position):
                    return child
            return None

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the Container (and its children).
            :param larger_surface: the surface to render into.
            """
            if self.surface.get_locked():
                return
            if not self.transparent:
                self.surface.fill(self.background_color)
            else:
                self.surface.fill((0, 0, 0, 0))
            for child in self.child_components:
                child.render(self.surface)
            super(GUI.Container, self).render(larger_surface)

        def refresh(self, children=True):
            # type: (bool) -> None
            """Updates the Container dimensions (and its children, optionally)
            :param children: true to call refresh() on children, false otherwise.
            """
            super(GUI.Container, self).refresh()
            if children:
                for child in self.child_components:
                    child.refresh()

    class AppContainer(Container):
        """A Container suited for applications.
        """

        def __init__(self, application):
            # type: (Application) -> None
            self.application = application
            self.dialogs = []
            self.dialog_screen_freezes = []
            self.dialog_components_freezes = []
            self.child_components = None
            self.scale_x = 1.0
            self.scale_y = 1.0
            if self.application.parameters.get("resize", False):
                # size = {"width": 240, "height": 320}
                d_w = float(self.application.parameters.get("size", GUI.DEFAULT_RESOLUTION).get("width"))
                d_h = float(self.application.parameters.get("size", GUI.DEFAULT_RESOLUTION).get("height"))
                self.scale_x = (state.gui.width / d_w)
                self.scale_y = (state.gui.height / d_h)
                super(GUI.AppContainer, self).__init__((0, 0), width=screen.get_width(),
                                                       height=screen.get_height() - 40,
                                                       resizable=True, fixedSize=True)
            else:
                super(GUI.AppContainer, self).__init__((0, 0), width=screen.get_width(),
                                                       height=screen.get_height() - 40,
                                                       resizable=False, fixedSize=True)

        def set_dialog(self, dialog):
            # type: (Union[Overlay, Dialog]) -> None
            """Pops up a Dialog or Overlay.
            :param dialog: the dialog to pop up.
            """
            self.dialogs.insert(0, dialog)
            self.dialog_components_freezes.insert(0, self.child_components[:])
            self.dialog_screen_freezes.insert(0, self.surface.copy())
            self.add_child(dialog.baseContainer)

        def clear_dialog(self):
            # type: () -> None
            """Closes the active dialog.
            """
            self.dialogs.pop(0)
            self.child_components = self.dialog_components_freezes[0]
            self.dialog_components_freezes.pop(0)
            self.dialog_screen_freezes.pop(0)

        # NOTE: changed in 1.01 - added largerSurface parameter to match base class method signature.
        def render(self, larger_surface=None):
            # type: (Any) -> None
            """Renders the AppContainer.
            :param larger_surface: this parameter is not relevant for this class.
            """
            if len(self.dialogs) == 0:
                super(GUI.AppContainer, self).render(self.surface)
            else:
                self.surface.blit(self.dialog_screen_freezes[0], (0, 0))
                self.dialogs[0].baseContainer.render(self.surface)
            screen.blit(self.surface, self.position)

        # NOTE: changed in 1.01 - added children parameter to match base class method signature.
        def refresh(self, children=False):
            # type: (Any) -> None
            """Updates the AppContainer dimensions.
            :param children: this parameter is not relevant for this class.
            :return:
            """
            self.width = screen.get_width()
            self.height = screen.get_height() - 40
            if self.application.parameters.get("resize", False):
                # size = {"width": 320}
                d_w = float(self.application.parameters.get("size", GUI.DEFAULT_RESOLUTION).get("width"))
                d_h = float(self.application.parameters.get("size", GUI.DEFAULT_RESOLUTION).get("height"))
                self.scale_x = 1.0 * (state.gui.width / d_w)
                self.scale_y = 1.0 * (state.gui.height / d_h)
                # super(GUI.AppContainer, self).refresh()

    class Text(Component):
        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, **data):
            # type: (Union[tuple, list], str, int, int, ...) -> None
            """Text instance initializer.
            :param position: the text screen coordinates.
            :param text: the text contents.
            :param color: the rendering color for the text.
            :param size: the size of the font.
            :param data: optional data related to this component.
            """
            # Defaults are "item" and 14.
            color, size = GUI.Component.default(color, state.color_palette.get_color(GUI.Palette.item), size, 14)
            self.text = text  # type: str
            self._original_text = text  # type: str
            self.size = size  # type: int
            self.color = color  # type: tuple
            self.font = data.get("font", state.font)  # type: GUI.Font
            self.use_freetype = data.get("freetype", False)  # type: bool
            self.responsive_width = data.get("responsive_width", True)  # type: bool
            data["surface"] = self.get_rendered_text()
            super(GUI.Text, self).__init__(position, **data)

        def get_rendered_text(self):
            # type: () -> pygame.Surface
            """Renders the text and return its surface.
            """
            r, g, b = self.color
            a = 255
            if self.use_freetype:
                return self.font.get(self.size, True).render(str(self.text), self.color)
            return self.font.get(self.size).render(self.text, 1, (r, g, b, a))

        def refresh(self):
            # type: () -> None
            """Re-renders the text.
            """
            self.surface = self.get_rendered_text()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders this Text.
            :param larger_surface: the surface to render onto.
            """
            if self.text != self._original_text:
                self.set_text(self.text)
            super(GUI.Text, self).render(larger_surface)

        def set_text(self, text):
            # type: (str) -> None
            """Sets the Text contents
            :param text: the new str.
            """
            self.text = str(text)
            self.refresh()
            if self.responsive_width:
                self.width = self.surface.get_width()
                self.height = self.surface.get_height()
            self.set_dimensions()

    class MultiLineText(Component):
        """Represents a text that wraps into multiple lines.
        """

        @staticmethod
        def render_textrect(string, font, rect, text_color, background_color, justification, use_ft):
            # type: (str, Union[pygame.Font, freetype.Font], pygame.Rect, tuple, tuple, int, bool) -> tuple
            final_lines = []
            requested_lines = string.splitlines()
            err = None
            for requested_line in requested_lines:
                if font.size(requested_line)[0] > rect.width:
                    words = requested_line.split(' ')
                    for word in words:
                        if font.size(word)[0] >= rect.width:
                            print("The word '{}' is too long to fit in the rect passed.".format(word))
                            err = 0
                    accumulated_line = ""
                    for word in words:
                        test_line = accumulated_line + word + " "
                        if font.size(test_line)[0] < rect.width:
                            accumulated_line = test_line
                        else:
                            final_lines.append(accumulated_line)
                            accumulated_line = word + " "
                    final_lines.append(accumulated_line)
                else:
                    final_lines.append(requested_line)
            surface = pygame.Surface(rect.size, pygame.SRCALPHA)
            surface.fill(background_color)
            accumulated_height = 0
            for line in final_lines:
                if accumulated_height + font.size(line)[1] >= rect.height:
                    err = 1
                if line != "":
                    # tempsurface = None
                    if use_ft:
                        tempsurface = font.render(line, text_color)
                    else:
                        tempsurface = font.render(line, 1, text_color)
                    if justification == 0:
                        surface.blit(tempsurface, (0, accumulated_height))
                    elif justification == 1:
                        surface.blit(tempsurface, ((rect.width - tempsurface.get_width()) / 2, accumulated_height))
                    elif justification == 2:
                        surface.blit(tempsurface, (rect.width - tempsurface.get_width(), accumulated_height))
                    else:
                        print("Invalid justification argument: {}".format(justification))
                        err = 2
                accumulated_height += font.size(line)[1]
            return surface, err, final_lines

        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, justification=DEFAULT, **data):
            # type: (tuple, str, int, int, int, ...) -> None
            """MultilineText instance initializer.
            :param position: the component position.
            :param text: the component's lines of text
            :param color: the text color
            :param size: the font size
            :param justification: 0 for left, 1 for centralized and 2 for right
            :param data: optional data related to the component.
            """
            # Defaults are "item", and 0 (left).
            color, size, justification = GUI.Component.default(color, state.color_palette.get_color(GUI.Palette.item),
                                                               size,
                                                               14,
                                                               justification, 0)
            self.justification = justification  # type: int
            self.color = color  # type: tuple
            self.size = size  # type: int
            self.text = str(text)  # type: str
            self.textSurface = None  # type: pygame.Surface
            self.font = data.get("font", state.font)  # type: GUI.Font
            self.use_freetype = data.get("freetype", False)  # type: bool
            super(GUI.MultiLineText, self).__init__(position, **data)

            self.refresh()
            if self.width > state.gui.width:
                self.width = state.gui.width

        def get_rendered_text(self):
            # type: () -> pygame.Surface
            """Render the text and returns its surface.
            """
            return GUI.MultiLineText.render_textrect(self.text, self.font.get(self.size, self.use_freetype),
                                                     pygame.Rect(0, 0, self.computed_width, self.computed_height),
                                                     self.color, (0, 0, 0, 0), self.justification, self.use_freetype)[0]

        def refresh(self):
            # type: () -> None
            """Re-renders the text.
            """
            super(GUI.MultiLineText, self).refresh()
            self.textSurface = self.get_rendered_text()
            self.surface.fill((0, 0, 0, 0))
            self.surface.blit(self.textSurface, (0, 0))

        def set_text(self, text):
            # type: (Union[str, unicode]) -> None
            """Sets the MultilineText's text.
            :param text: the new text.
            """
            self.text = text if isinstance(text, (str, unicode)) else str(text)
            self.set_dimensions()
            self.refresh()

    class ExpandingMultiLineText(MultiLineText):
        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, justification=DEFAULT, line_height=DEFAULT,
                     **data):
            # type: (Union[tuple, list], str, int, int, int, int, ...) -> None
            """ExpandingMultilineText instance initializer.
            :param position: the component's position.
            :param text: the component's contents.
            :param color: the color of the text.
            :param size: the size of the font.
            :param justification: 0 for left, 1 for centralized and 2 for right justification
            :param line_height: the spacing between lines of text.
            :param data: optional data related to the component.
            """
            # Defaults are "item", 14, 0, and 16.
            color, size, justification, line_height = GUI.Component.default(color,
                                                                            state.color_palette.get_color(
                                                                                GUI.Palette.item),
                                                                            size, 14,
                                                                            justification, 0,
                                                                            line_height, 16)
            self.line_height = line_height
            self.linked_scroller = data.get("scroller", None)
            self.text_lines = []
            super(GUI.ExpandingMultiLineText, self).__init__(position, text, color, size, justification, **data)
            self.height = self.computed_height
            self.refresh()

        def get_rendered_text(self):
            fits = False
            surf = None
            while not fits:
                d = GUI.MultiLineText.render_textrect(self.text, self.font.get(self.size),
                                                      pygame.Rect(self.computed_position[0], self.computed_position[1],
                                                                  self.computed_width, self.height),
                                                      self.color, (0, 0, 0, 0), self.justification, self.use_freetype)

                surf = d[0]  # type: pygame.Surface
                fits = d[1] != 1  # type: bool
                self.text_lines = d[2]  # type: list
                if not fits:
                    self.height += self.line_height
                    self.computed_height = self.height

            if self.linked_scroller is not None:
                self.linked_scroller.refresh(False)
            return surf

    class Image(Component):
        """Represents visual contents such as pictures, icons and similar.
        """

        def __init__(self, position, **data):
            # type: (Union[tuple, list], ...) -> None
            """Image instance initializer.
            :param position: the Image position.
            :param data: optional data related to the component.
            """
            self.path = ""
            self.original_surface = None
            self.transparent = True  # type: bool
            self.resize_image = data.get("resize_image", True)  # type: bool
            if "path" in data:
                self.path = data["path"]
            else:
                self.path = "surface"
            if "surface" not in data:
                data["surface"] = pygame.image.load(data["path"])
            self.original_surface = data["surface"]  # type: pygame.Surface
            self.original_width = self.original_surface.get_width()  # type: int
            self.original_height = self.original_surface.get_height()  # type: int
            super(GUI.Image, self).__init__(position, **data)
            if self.resize_image:
                self.set_surface(
                    pygame.transform.scale(self.original_surface, (self.computed_width, self.computed_height)))

        def set_image(self, **data):
            # type: (...) -> None
            """Sets the Image resource.
            :param data:
            :return:
            """
            self.path = data.get("path", "surface")
            if "surface" not in data:
                data["surface"] = pygame.image.load(data["path"])
            self.original_surface = data["surface"]
            if data.get("resize", False):
                self.width = self.original_surface.get_width()
                self.height = self.original_surface.get_height()
            self.refresh()

        def refresh(self):
            # type: () -> None
            """Updates the Image resource.
            """
            if self.resize_image:
                self.set_surface(pygame.transform.scale(
                    self.original_surface, (self.computed_width, self.computed_height)))
            else:
                super(GUI.Image, self).refresh()

    class Slider(Component):

        def __init__(self, position, initial_pct=0, **data):
            super(GUI.Slider, self).__init__(position, **data)
            self._percent = initial_pct
            self.background_color = data.get("backgroundColor", state.color_palette.get_color(GUI.Palette.background))
            self.color = data.get("color", state.color_palette.get_color(GUI.Palette.item))
            self.slider_color = data.get("sliderColor", state.color_palette.get_color(GUI.Palette.accent))
            self.on_change_method = data.get("onChange", Application.dummy)
            self.percent_pixels = self.computed_width / 100.0
            self.refresh()

        def on_change(self):
            # type: () -> None
            """Called when the slider is dragged.
            """
            self.on_change_method(self._percent)

        @property
        def percent(self):
            """Sets the slider scroll relative position.
            """
            return self._percent

        @percent.setter
        def percent(self, value):
            # type: (int) -> None
            self._percent = value

        def refresh(self):
            # type: () -> None
            """Updates the slider position.
            """
            self.percent_pixels = self.computed_width / 100.0
            super(GUI.Slider, self).refresh()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the slider.
            :param larger_surface: the surface to render onto.
            """
            self.surface.fill(self.background_color)
            pygame.draw.rect(self.surface, self.color,
                             [0, self.computed_height / 4, self.computed_width, self.computed_height / 2])
            pygame.draw.rect(self.surface, self.slider_color,
                             [(self._percent * self.percent_pixels) - 15, 0, 30, self.computed_height])
            super(GUI.Slider, self).render(larger_surface)

        def check_click(self, mouse_event, offset_x=0, offset_y=0):
            is_clicked = super(GUI.Slider, self).check_click(mouse_event, offset_x, offset_y)
            if is_clicked:
                self._percent = (mouse_event.pos[0] - offset_x - self.computed_position[0]) / self.percent_pixels
                if self._percent > 100.0:
                    self._percent = 100.0
                self.on_change()
            return is_clicked

    class Button(Container):

        def __init__(self, position, text, bg_color=DEFAULT, text_color=DEFAULT, text_size=DEFAULT, **data):
            # type: (tuple, str, tuple, tuple, int, ...) -> None
            """Button instance initializer.
            :param position: the button position.
            :param text: the button text
            :param bg_color: the button background color
            :param text_color: the color of the button text
            :param text_size: the size of the button text
            :param data: optional data related to the button.
            """
            # Defaults are "darker:background", "item", and 14.
            bg_color, text_color, text_size = GUI.Component.default(bg_color,
                                                                    state.color_palette.get_color(
                                                                        GUI.Palette.background,
                                                                        GUI.ColorBrightness.darker),
                                                                    text_color,
                                                                    state.color_palette.get_color(GUI.Palette.item),
                                                                    text_size, 14)
            self.text_component = GUI.Text((0, 0), text, text_color, text_size, font=data.get("font", state.font),
                                           freetype=data.get("freetype", False))
            self.padding_amount = data.get("padding", 5)
            if "width" not in data:
                data["width"] = self.text_component.computed_width + (2 * self.padding_amount)
            if "height" not in data:
                data["height"] = self.text_component.computed_height + (2 * self.padding_amount)
            super(GUI.Button, self).__init__(position, **data)
            self.SKIP_CHILD_CHECK = True
            self.text_component.set_position(GUI.get_centered_coordinates(self.text_component, self))
            self.background_color = bg_color
            self.add_child(self.text_component)

        def set_dimensions(self):
            # type: () -> None
            """Adjusts the button text position based on its bounds.
            """
            super(GUI.Button, self).set_dimensions()
            self.text_component.set_position(GUI.get_centered_coordinates(self.text_component, self))

        def set_text(self, text):
            # type: (str) -> None
            """Sets the button text.

            :param text: the text value to set.
            """
            self.text_component.set_text(text)
            self.set_dimensions()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the button onto given surface.
            """
            super(GUI.Button, self).render(larger_surface)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.Container
            """Overrides Container.get_clicked_child()
            """
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

    class Checkbox(Component):

        def __init__(self, position, checked=False, **data):
            # type: (tuple, bool, ...) -> None
            """Checkbox instance initializer.

            :param position: the checkbox position.
            :param checked: whether the checkbox is checked or not.
            :param data: optional data related to the checkbox.
            """
            if "border" not in data:
                data["border"] = 2
                data["borderColor"] = state.color_palette.get_color(GUI.Palette.item)
            super(GUI.Checkbox, self).__init__(position, **data)
            self.background_color = data.get("backgroundColor", state.color_palette.get_color(GUI.Palette.background))
            self.check_color = data.get("checkColor", state.color_palette.get_color(GUI.Palette.accent))
            self.check_width = data.get("checkWidth", self.computed_height / 4)
            self._checked = checked
            self.internal_click_overrides[GUI.CompEvt.on_click] = [self.check, ()]

        @property
        def checked(self):
            return self._checked

        def check(self, check_state=CheckboxState.toggle):
            # type: (int) -> None
            """Sets the checkbox check state.
            :param check_state: one of CheckboxState values.
            """
            if check_state == CheckboxState.toggle:
                self._checked = not self._checked
            else:
                self._checked = check_state == CheckboxState.checked

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the checkbox.
            :param larger_surface: the surface to render onto.
            """
            self.surface.fill(self.background_color)
            if self._checked:
                pygame.draw.lines(self.surface, self.check_color, False, [(0, self.computed_height / 2),
                                                                          (self.computed_width / 2,
                                                                           self.computed_height - self.check_width / 2),
                                                                          (self.computed_width, 0)], self.check_width)
            super(GUI.Checkbox, self).render(larger_surface)


    class Switch(Component):
        """Represents a toggle button.
        """

        def __init__(self, position, on=False, **data):
            # type: (tuple, bool, ...) -> None
            """Switch instance initializer.
            :param position: the switch position.
            :param on: whether its on or off.
            :param data: optional data related to the switch.
            """
            if "border" not in data:
                data["border"] = 2
                data["borderColor"] = state.color_palette.get_color(GUI.Palette.item)
            super(GUI.Switch, self).__init__(position, **data)
            self.background_color = data.get("backgroundColor", state.color_palette.get_color(GUI.Palette.background))
            self.on_color = data.get("onColor", state.color_palette.get_color(GUI.Palette.accent))
            self.off_color = data.get("offColor", state.color_palette.get_color(GUI.Palette.background,
                                                                                GUI.ColorBrightness.dark))
            self.on = on
            self.internal_click_overrides[GUI.CompEvt.on_click] = [self.switch, ()]

        # NOTE: changed in 1.01 - getChecked() turned into a property
        @property
        def checked(self):
            # type: () -> bool
            """Gets whether the switch is on.
            """
            return self.on

        def switch(self, switch_state=SwitchState.toggle):
            # type: (int) -> None
            """Sets the switch state.
            :param switch_state: one of GUI.SwitchState values.
            """
            if switch_state == SwitchState.toggle:
                self.on = not self.on
            else:
                self.on = switch_state == GUI.SwitchState.on

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the switch.
            """
            self.surface.fill(self.background_color)
            if self.on:
                pygame.draw.rect(self.surface, self.on_color,
                                 [self.computed_width / 2, 0, self.computed_width / 2, self.computed_height])
            else:
                pygame.draw.rect(self.surface, self.off_color, [0, 0, self.computed_width / 2, self.computed_height])
            pygame.draw.circle(self.surface, state.color_palette.get_color(GUI.Palette.item),
                               (self.computed_width / 4, self.computed_height / 2), self.computed_height / 4, 2)
            pygame.draw.line(self.surface, state.color_palette.get_color(GUI.Palette.item),
                             (3 * (self.computed_width / 4), self.computed_height / 4),
                             (3 * (self.computed_width / 4), 3 * (self.computed_height / 4)), 2)
            super(GUI.Switch, self).render(larger_surface)

    # WARNING: this class is not used.
    class Canvas(Component):
        def __init__(self, position, **data):
            super(GUI.Canvas, self).__init__(position, **data)

    class KeyboardButton(Container):
        """Represents a input method editor's button.
        """

        def __init__(self, position, symbol, alt_symbol, **data):
            # type: (tuple, str, str, ...) -> None
            """KeyboardButton instance initializer.
            :param position: the button position
            :param symbol: the primary input character or command
            :param alt_symbol: the secondary input character or command
            :param data: optional data related to the keybard button
            """
            if "border" not in data:
                data["border"] = 1
                data["borderColor"] = state.color_palette.get_color(GUI.Palette.item)
            super(GUI.KeyboardButton, self).__init__(position, **data)
            self.SKIP_CHILD_CHECK = True
            self.primary_text_component = GUI.Text((1, 0), symbol, state.color_palette.get_color(GUI.Palette.item), 20,
                                                   font=data.get("font", state.typing_font))
            self.secondary_text_component = GUI.Text((self.computed_width - 8, 0), alt_symbol,
                                                     state.color_palette.get_color(GUI.Palette.item), 10,
                                                     font=data.get("font", state.typing_font))
            self.primary_text_component.set_position(
                [GUI.get_centered_coordinates(self.primary_text_component, self)[0] - 6,
                 self.computed_height - self.primary_text_component.computed_height - 1])
            self.add_child(self.primary_text_component)
            self.add_child(self.secondary_text_component)
            self.blink_time = 0
            self.internal_click_overrides[GUI.CompEvt.on_click] = (self.register_blink, ())
            self.internal_click_overrides[GUI.CompEvt.on_longclick] = (self.register_blink, (True,))

        def register_blink(self, lp=False):
            # type: (bool) -> None
            self.blink_time = state.gui.update_interval / 4
            self.primary_text_component.color = state.color_palette.get_color(GUI.Palette.background)
            self.secondary_text_component.color = state.color_palette.get_color(GUI.Palette.background)
            self.background_color = state.color_palette.get_color(GUI.Palette.accent if lp else GUI.Palette.item)
            self.refresh()

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.KeyboardButton
            """Overrides Container.get_clicked_child()
            """
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the keyboard button.
            :param larger_surface: the surface to render onto.
            """
            if self.blink_time >= 0:
                self.blink_time -= 1
                if self.blink_time < 0:
                    self.primary_text_component.color = state.color_palette.get_color(GUI.Palette.item)
                    self.secondary_text_component.color = state.color_palette.get_color(GUI.Palette.item)
                    self.background_color = state.color_palette.get_color(GUI.Palette.background)
                    self.refresh()
            super(GUI.KeyboardButton, self).render(larger_surface)

    class TextEntryField(Container):
        """Represents a box to input text.
        """

        def __init__(self, position, initial_text="", **data):
            # type: (tuple, str, ...) -> None
            """TextEntryField instance initializer.
            :param position: the entry field position
            :param initial_text: the initial entry contents
            :param data: optional data related to the entry field
            """
            if "border" not in data:
                data["border"] = 1
                data["borderColor"] = state.color_palette.get_color(GUI.Palette.accent)
            if "textColor" not in data:
                data["textColor"] = state.color_palette.get_color(GUI.Palette.item)
            if "blink" in data:
                self.blink_interval = data["blink"]
            else:
                self.blink_interval = 500
            self.do_blink = True
            self.blink_on = False
            self.last_blink = datetime.now()
            self.indicator_position = len(initial_text)
            self.indicator_px_position = 0
            super(GUI.TextEntryField, self).__init__(position, **data)
            self.SKIP_CHILD_CHECK = True
            self.text_component = GUI.Text((2, 0), initial_text, data["textColor"], 16, font=state.typing_font)
            self.update_overflow()
            self.last_click_coord = None
            self.text_component.position[1] = GUI.get_centered_coordinates(self.text_component, self)[1]
            self.add_child(self.text_component)
            self.MULTILINE = None
            self.internal_click_overrides[GUI.CompEvt.on_click] = (self.activate, ())
            self.internal_click_overrides[GUI.CompEvt.on_intermediate_updt] = (self.drag_scroll, ())
            self.overflow = max(self.text_component.computed_width - (self.computed_width - 4), 0)

        def clear_scroll_params(self):
            # type: () -> None
            self.last_click_coord = None

        def drag_scroll(self):
            # type: () -> None
            """Scrolls the text.
            """
            if self.last_click_coord is not None and self.overflow > 0:
                ydist = self._inner_click_coordinates[1] - self.last_click_coord[1]
                self.overflow -= ydist
                if self.overflow > 0 and self.overflow + self.computed_width < self.text_component.computed_width:
                    self.text_component.position[0] = 2 - self.overflow
                else:
                    self.text_component.position[0] = 2
            self.last_click_coord = self._inner_click_coordinates

        def get_px_position(self, from_pos=DEFAULT):
            # type: (int) -> int
            """?
            :param from_pos: ?
            """
            return state.typing_font.get(16).render(
                self.text_component.text[:(self.indicator_position if from_pos == DEFAULT else from_pos)], 1,
                self.text_component.color).get_width()

        def activate(self):
            # type: () -> GUI.TextEntryField
            self.clear_scroll_params()
            self.update_overflow()
            state.keyboard = GUI.Keyboard(self)
            if self.MULTILINE is not None:
                for f in self.MULTILINE.textFields:
                    f.doBlink = False
            self.do_blink = True
            mouse_pos = self._inner_click_coordinates[0] - self.inner_offset[0]
            if mouse_pos > self.text_component.computed_width:
                self.indicator_position = len(self.text_component.text)
            else:
                prev_width = 0
                for self.indicator_position in range(len(self.text_component.text)):
                    curr_width = self.get_px_position(self.indicator_position)
                    if mouse_pos >= prev_width and mouse_pos <= curr_width:
                        self.indicator_position -= 1
                        break
                    prev_width = curr_width
            state.keyboard.active = True
            self.indicator_px_position = self.get_px_position()
            if self.MULTILINE:
                self.MULTILINE.set_current(self)
            return self

        def update_overflow(self):
            # type: () -> None
            """Acomodates the text in its bounds.
            """
            self.overflow = max(self.text_component.computed_width - (self.computed_width - 4), 0)
            if self.overflow > 0:
                self.text_component.position[0] = 2 - self.overflow
            else:
                self.text_component.position[0] = 2

        def append_char(self, char):
            # type: (str) -> None
            """Inserts or appends a text character in the caret position.
            :param char: the character to append or insert
            """
            if self.indicator_position == len(self.text_component.text) - 1:
                self.text_component.text += char
            else:
                self.text_component.text = self.text_component.text[
                                           :self.indicator_position] + char + self.text_component.text[
                                                                              self.indicator_position:]
            self.text_component.refresh()
            self.indicator_position += len(char)
            self.update_overflow()
            if self.MULTILINE is not None:
                if self.overflow > 0:
                    newt = self.text_component.text[max(self.text_component.text.rfind(" "),
                                                        self.text_component.text.rfind("-")):]
                    self.text_component.text = self.text_component.text.rstrip(newt)
                    self.MULTILINE.add_field(newt)
                    self.MULTILINE.wrappedLines.append(self.MULTILINE.currentField)
                    # if self.MULTILINE.currentField == len(self.MULTILINE.textFields)-1:
                    #    self.MULTILINE.addField(newt)
                    # else:
                    #    self.MULTILINE.prependToNextField(newt)
                    self.text_component.refresh()
                    self.update_overflow()
            self.indicator_px_position = self.get_px_position()

        def backspace(self):
            # type: () -> None
            """Erases a character at the left of the caret.
            """
            if self.indicator_position >= 1:
                self.indicator_position -= 1
                self.indicator_px_position = self.get_px_position()
                self.text_component.text = self.text_component.text[
                                           :self.indicator_position] + self.text_component.text[
                                                                       self.indicator_position + 1:]
                self.text_component.refresh()
            else:
                if self.MULTILINE is not None and self.MULTILINE.currentField > 0:
                    self.MULTILINE.remove_field(self)
                    self.MULTILINE.textFields[self.MULTILINE.currentField - 1].append_char(
                        self.text_component.text.strip(" "))
                    self.MULTILINE.textFields[self.MULTILINE.currentField - 1].activate()
            self.update_overflow()

        def delete(self):
            # type: () -> None
            """Erases a character at the right of the caret.
            """
            if self.indicator_position < len(self.text_component.text):
                self.text_component.text = self.text_component.text[
                                           :self.indicator_position] + self.text_component.text[
                                                                       self.indicator_position + 1:]
                self.text_component.refresh()
            self.update_overflow()
            if self.MULTILINE is not None:
                self.append_char(self.MULTILINE.get_delete_char())

        def get_text(self):
            # type: () -> str
            return self.text_component.text

        # NOTE: changed in 1.01 - added chidren parameter to match base class method signature.
        def refresh(self, children=False):
            # type: (bool) -> None
            """
            :param children: this parameter is not relevant for this method.
            :return:
            """
            self.update_overflow()
            super(GUI.TextEntryField, self).refresh()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders this entry field.
            """
            if not self.transparent:
                self.surface.fill(self.background_color)
            else:
                self.surface.fill((0, 0, 0, 0))
            for child in self.child_components:
                child.render(self.surface)
            if self.do_blink:
                if ((datetime.now() - self.last_blink).microseconds / 1000) >= self.blink_interval:
                    self.last_blink = datetime.now()
                    self.blink_on = not self.blink_on
                if self.blink_on:
                    pygame.draw.rect(self.surface, self.text_component.color,
                                     [self.indicator_px_position, 2, 2, self.computed_height - 4])
            super(GUI.Container, self).render(larger_surface)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.TextEntryField
            """Overrides Container.get_clicked_child.
            """
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

    class PagedContainer(Container):

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """PagedContainer instance initializer.
            :param position: container position.
            :param data: optional data related to the paged container.
            """
            super(GUI.PagedContainer, self).__init__(position, **data)
            self.pages = data.get("pages", [])
            self.current_page = 0
            self.hide_controls = data.get("hideControls", False)
            self.page_controls = GUI.Container((0, self.computed_height - 20),
                                               color=state.color_palette.get_color(GUI.Palette.background),
                                               width=self.computed_width, height=20)
            self.page_left_button = GUI.Button((0, 0), " < ", state.color_palette.get_color(GUI.Palette.item),
                                               state.color_palette.get_color(GUI.Palette.accent),
                                               16, width=40, height=20, onClick=self.page_left,
                                               onLongClick=self.go_to_page)
            self.page_right_button = GUI.Button((self.computed_width - 40, 0), " > ",
                                                state.color_palette.get_color(GUI.Palette.item),
                                                state.color_palette.get_color(GUI.Palette.accent),
                                                16, width=40, height=20, onClick=self.page_right,
                                                onLongClick=self.go_to_last_page)
            self.page_indicator_text = GUI.Text((0, 0), str(self.current_page + 1) + " of " + str(len(self.pages)),
                                                state.color_palette.get_color(GUI.Palette.item),
                                                16)
            self.page_holder = GUI.Container((0, 0), color=state.color_palette.get_color(GUI.Palette.background),
                                             width=self.computed_width, height=(
                    self.computed_height - 20 if not self.hide_controls else self.computed_height))
            self.page_indicator_text.position[0] = GUI.get_centered_coordinates(self.page_indicator_text,
                                                                                self.page_controls)[0]
            super(GUI.PagedContainer, self).add_child(self.page_holder)
            self.page_controls.add_child(self.page_left_button)
            self.page_controls.add_child(self.page_indicator_text)
            self.page_controls.add_child(self.page_right_button)
            if not self.hide_controls:
                super(GUI.PagedContainer, self).add_child(self.page_controls)

        def add_page(self, page):
            # type: (GUI.Container) -> None
            """Adds a page.
            """
            self.pages.append(page)
            self.page_indicator_text.text = str(self.current_page + 1) + " of " + str(len(self.pages))
            self.page_indicator_text.refresh()

        def get_page(self, number):
            # type: (int) -> GUI.Container
            return self.pages[number]

        def page_left(self):
            # type: () -> None
            """Go to next page at the left.
            """
            if self.current_page >= 1:
                self.go_to_page(self.current_page - 1)

        def page_right(self):
            # type: () -> None
            """Go to next page at the right.
            """
            if self.current_page < len(self.pages) - 1:
                self.go_to_page(self.current_page + 1)

        def go_to_page(self, number=0):
            # type: (int) -> None
            """Go to the page at given index.
            """
            self.current_page = number
            self.page_holder.clear_children()
            self.page_holder.add_child(self.get_page(self.current_page))
            self.page_indicator_text.set_text(str(self.current_page + 1) + " of " + str(len(self.pages)))
            self.page_indicator_text.refresh()

        def go_to_last_page(self):
            # type: () -> None
            """Go to leftmost page.
            """
            self.go_to_page(len(self.pages) - 1)

        def get_last_page(self):
            # type: () -> GUI.Container
            """Returns the leftmost page.
            """
            return self.pages[len(self.pages) - 1]

        def generate_page(self, **data):
            # type: (...) -> GUI.Container
            """Generates a page.
            """
            if "width" not in data:
                data["width"] = self.page_holder.computed_width
            if "height" not in data:
                data["height"] = self.page_holder.computed_height
            data["isPage"] = True
            return GUI.Container((0, 0), **data)

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a child component.
            """
            if isinstance(self.pages, list):
                self.add_page(self.generate_page(color=self.background_color, width=self.page_holder.computed_width,
                                                 height=self.page_holder.computed_height))
            self.get_last_page().add_child(component)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            """Removes a child component.
            """
            self.pages[self.current_page].remove_child(component)
            children_copy = self.pages[self.current_page].child_components[:]
            for page in self.pages:
                for child in page.child_components:
                    page.remove_child(child)
            for child in children_copy:
                self.add_child(child)

        def remove_page(self, page):
            # type: (Union[GUI.Container, int]) -> None
            """Removes a page by its index or instance.
            """
            if isinstance(page, int):
                self.pages.pop(page)
            else:
                self.pages.remove(page)
            if self.current_page >= len(self.pages):
                self.go_to_page(self.current_page - 1)

        def clear_children(self):
            # type: () -> None
            """Removes all child components.
            """
            self.pages = []
            self.add_page(self.generate_page(color=self.background_color))
            self.go_to_page()

    class GriddedPagedContainer(PagedContainer):
        """Represents a PagedContainer with grid layout.
        """

        def __init__(self, position, rows=5, columns=4, **data):
            # type: (tuple, int, int, ...) -> None
            """GriddedPagedContainer instance initializer.
            :param position: the container position.
            :param rows: the number of grid rows
            :param columns: the number to grid columns
            :param data: optional data related to the container
            """
            self.padding = 5
            if "padding" in data:
                self.padding = data["padding"]
            self.rows = rows
            self.columns = columns
            super(GUI.PagedContainer, self).__init__(position, **data)
            self.per_row = ((self.computed_height - 20) - (2 * self.padding)) / rows
            self.per_column = (self.computed_width - (2 * self.padding)) / columns
            super(GUI.GriddedPagedContainer, self).__init__(position, **data)

        def is_page_filled(self, number):
            # type: (Union[Component, int]) -> bool
            """Returns whether the component grid is filled with components."""
            if isinstance(number, int):
                return len(self.pages[number].child_components) == (self.rows * self.columns)
            else:
                return len(number.child_components) == (self.rows * self.columns)

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a child component.
            """
            if self.pages == [] or self.is_page_filled(self.get_last_page()):
                self.add_page(self.generate_page(color=self.background_color))
            new_child_position = [self.padding, self.padding]
            if isinstance(self.get_last_page().child_components, list):
                component.set_position(new_child_position)
                self.get_last_page().add_child(component)
                return
            last_child_position = self.get_last_page().child_components[-1].computed_position[:]
            if last_child_position[0] < self.padding + (self.per_column * (self.columns - 1)):
                new_child_position = [last_child_position[0] + self.per_column, last_child_position[1]]
            else:
                new_child_position = [self.padding, last_child_position[1] + self.per_row]
            component.set_position(new_child_position)
            self.get_last_page().add_child(component)

    class ListPagedContainer(PagedContainer):
        """Represents a PagedContainer with list layout.
        """

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """ListPagedContainer instance initializer.
            :param position: the container position
            :param data: optional data related to the list paged container
            """
            self.padding = data.get("padding", 0)
            self.margin = data.get("margin", 0)
            super(GUI.ListPagedContainer, self).__init__(position, **data)

        def get_height_of_components(self):
            # type: () -> int
            """Returns the vertical length in pixels of the list
            """
            height = self.padding
            if len(self.pages) == 0:
                return self.padding
            for component in self.get_last_page().child_components:
                height += component.computedHeight + (2 * self.margin)
            return height

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a child component.
            """
            component_height = self.get_height_of_components()
            if self.pages == [] or (component_height + (component.computed_height + 2 * self.margin) +
                                    (2 * self.padding)) >= self.page_holder.computed_height:
                self.add_page(self.generate_page(color=self.background_color))
                component_height = self.get_height_of_components()
            component.set_position([self.padding, component_height])
            self.get_last_page().add_child(component)
            component.refresh()

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            """Removes a child component.
            """
            super(GUI.ListPagedContainer, self).remove_child(component)
            if len(self.pages[0].childComponents) == 0:
                self.remove_page(0)
                self.go_to_page()

    class ButtonRow(Container):
        """Represents a sequence of adjacent buttons.
        """

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """ButtonRow instance initializer.

            :param position: the container position.
            :param data: optional data related to the button row.
            """
            self.padding = data.get("padding", 0)
            self.margin = data.get("margin", 0)
            super(GUI.ButtonRow, self).__init__(position, **data)

        def get_last_component(self):
            # type: () -> GUI.Component
            """Returns the last button of the row.
            """
            if len(self.child_components) > 0:
                return self.child_components[-1]
            return None

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a child component.
            """
            component.height = self.computed_height - (2 * self.padding)
            last = self.get_last_component()
            if last is not None:
                component.set_position([last.computed_position[0] + last.computed_width + self.margin, self.padding])
            else:
                component.set_position([self.padding, self.padding])
            component.set_dimensions()
            super(GUI.ButtonRow, self).add_child(component)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            """Removes a child component.
            """
            super(GUI.ButtonRow, self).remove_child(component)
            children_copy = self.child_components[:]
            self.clear_children()
            for child in children_copy:
                self.add_child(child)

    class ScrollIndicator(Component):
        """TODO: describe it.
        """

        def __init__(self, scroll_cont, position, color, **data):
            # type: (GUI.ScrollableContainer, tuple, tuple, ...) -> None
            """ScrollIndicator instance initializer.
            :param scroll_cont: the scroll container
            :param position: the indicator position
            :param color: the color of the indicator
            :param data: optional data related to the scroll indicator
            """
            super(GUI.ScrollIndicator, self).__init__(position, **data)
            self.internal_click_overrides[GUI.CompEvt.on_intermediate_updt] = (self.drag_scroll, ())
            self.internal_click_overrides[GUI.CompEvt.on_click] = (self.clear_scroll_params, ())
            self.internal_click_overrides[GUI.CompEvt.on_longclick] = (self.clear_scroll_params, ())
            self.scroll_container = scroll_cont  # type: GUI.ScrollableContainer
            self.color = color  # type: tuple
            self.last_click_coord = None  # type: tuple
            self.pct = 0.0
            self.slide = 0.0
            self.sih = 0.0

        def update(self):
            # type: () -> None
            """Updates the indicator.
            """
            self.pct = 1.0 * self.scroll_container.computed_height / (
                self.scroll_container.max_offset - self.scroll_container.min_offset)
            self.slide = -self.scroll_container.offset * self.pct
            self.sih = self.pct * self.computed_height

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the scroll indicator.
            """
            self.surface.fill(self.color)
            pygame.draw.rect(self.surface, state.color_palette.get_color(GUI.Palette.accent),
                             [0, int(self.slide * (1.0 * self.computed_height / self.scroll_container.computed_height)),
                              self.computed_width, int(self.sih)])
            super(GUI.ScrollIndicator, self).render(larger_surface)

        def clear_scroll_params(self):
            # type: () -> None
            """Deletes the last click coordinate.
            """
            self.last_click_coord = None

        def drag_scroll(self):
            # type: () -> None
            """Updates the container scroll position.
            """
            if self.last_click_coord is not None:
                ydist = self._inner_click_coordinates[1] - self.last_click_coord[1]
                self.scroll_container.scroll(ydist)
            self.last_click_coord = self._inner_click_coordinates

    class ScrollableContainer(Container):
        """Represents a Container that can scroll in or out of
        view the contents that does not fit entirely in its bounds.
        """

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """ScrollableContainer instance initializer.
            :param position: the container position
            :param data: optional data related to the scrollable container
            """
            self.scroll_amount = data.get("scrollAmount", state.gui.height / 8)
            super(GUI.ScrollableContainer, self).__init__(position, **data)
            self.container = GUI.Container((0, 0), transparent=True, width=self.computed_width - 20,
                                           height=self.computed_height)
            self.scroll_bar = GUI.Container((self.computed_width - 20, 0), width=20, height=self.computed_height)
            self.scroll_upbtn = GUI.Image((0, 0), path="res/scrollup.png", width=20, height=40,
                                          onClick=self.scroll, onClickData=(self.scroll_amount,))
            self.scroll_downbtn = GUI.Image((0, self.scroll_bar.computed_height - 40), path="res/scrolldown.png",
                                            width=20, height=40,
                                            onClick=self.scroll, onClickData=(-self.scroll_amount,))
            self.scroll_indicator = GUI.ScrollIndicator(self, (0, 40), self.background_color, width=20,
                                                        height=self.scroll_bar.computed_height - 80, border=1,
                                                        borderColor=state.color_palette.get_color(GUI.Palette.item))
            if self.computed_height >= 120:
                self.scroll_bar.add_child(self.scroll_indicator)
            self.scroll_bar.add_child(self.scroll_upbtn)
            self.scroll_bar.add_child(self.scroll_downbtn)
            super(GUI.ScrollableContainer, self).add_child(self.container)
            super(GUI.ScrollableContainer, self).add_child(self.scroll_bar)
            self.offset = 0
            self.min_offset = 0
            self.max_offset = self.container.computed_height
            self.scroll_indicator.update()

        def scroll(self, amount):
            # type: (int) -> None
            """Scrolls the contents.
            :param amount: the scrolling amount in pixels
            """
            if amount < 0:
                if self.offset - amount - self.computed_height <= -self.max_offset:
                    return
            else:
                if self.offset + amount > self.min_offset:
                    # self.offset = -self.minOffset
                    return
            for child in self.container.child_components:
                child.position[1] = child.computedPosition[1] + amount
            self.offset += amount
            self.scroll_indicator.update()

        def get_visible_children(self):
            # type: () -> list
            """Returns all child components that are not out of view.
            """
            visible = []
            for child in self.container.child_components:
                if (child.computedPosition[1] + child.computedHeight >= -10 and
                        child.computedPosition[1] - child.computedHeight <= self.computed_height + 10):
                    visible.append(child)
            return visible

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.Component
            if not self.check_click(mouse_event, offset_x, offset_y):
                return None
            clicked = self.scroll_bar.get_clicked_child(mouse_event, offset_x + self.computed_position[0],
                                                        offset_y + self.computed_position[1])
            if clicked is not None:
                return clicked
            visible = self.get_visible_children()
            for child in reversed(visible[:]):
                if hasattr(child, "SKIP_CHILD_CHECK"):
                    if child.SKIP_CHILD_CHECK:
                        if child.check_click(mouse_event, offset_x + self.computed_position[0],
                                             offset_y + self.computed_position[1]):
                            return child
                        else:
                            continue
                    else:
                        sub_check = child.get_clicked_child(mouse_event, offset_x + self.computed_position[0],
                                                            offset_y + self.computed_position[1])
                        if sub_check is None:
                            continue
                        return sub_check
                else:
                    if child.check_click(mouse_event, offset_x + self.computed_position[0],
                                         offset_y + self.computed_position[1]):
                        return child
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a child component.
            """
            if component.computed_position[1] < self.min_offset:
                self.min_offset = component.computed_position[1]
            if component.computed_position[1] + component.computed_height > self.max_offset:
                self.max_offset = component.computed_position[1] + component.computed_height
            self.container.add_child(component)
            self.scroll_indicator.update()

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            """Removes a child component
            """
            self.container.remove_child(component)
            if component.computed_position[1] == self.min_offset:
                self.min_offset = 0
                for comp in self.container.child_components:
                    if comp.computed_position[1] < self.min_offset:
                        self.min_offset = comp.computed_position[1]
            if component.computed_position[1] == self.max_offset:
                self.max_offset = self.computed_height
                for comp in self.container.child_components:
                    if comp.computed_position[1] + comp.computed_height > self.max_offset:
                        self.max_offset = comp.computed_position[1] + comp.computed_height
            self.scroll_indicator.update()

        def clear_children(self):
            # type: () -> None
            """Removes all child components.
            """
            self.container.clear_children()
            self.max_offset = self.computed_height
            self.offset = 0
            self.scroll_indicator.update()

        def render(self, larger_surface):
            # type: (pygameSurface) -> None
            """Renders the scrollable container.
            """
            super(GUI.ScrollableContainer, self).render(larger_surface)

        def refresh(self, children=True):
            # type: (bool) -> None
            """Updates the scrollable container.
            """
            super(GUI.ScrollableContainer, self).refresh()
            self.min_offset = 0
            for comp in self.container.child_components:
                if comp.computed_position[1] < self.min_offset:
                    self.min_offset = comp.computed_position[1]
            self.max_offset = self.computed_height
            for comp in self.container.child_components:
                if comp.computed_position[1] + comp.computed_height > self.max_offset:
                    self.max_offset = comp.computed_position[1] + comp.computed_height
            self.scroll_indicator.update()
            self.container.refresh(children)

    class ListScrollableContainer(ScrollableContainer):
        """Represents a scrollable container that behaves as a list.
        """

        def __init__(self, position, **data):
            # type: (tuple, ...) -> None
            """ListScrollableContainer instance initializer.
            :param position: the list position
            :param data: optional data related to the list scrollable
            """
            self.margin = data.get("margin", 0)
            super(GUI.ListScrollableContainer, self).__init__(position, **data)

        def get_cumulative_height(self):
            # type: () -> int
            """Returns the vertical length in pixels of the list.
            """
            height = 0
            if len(self.container.child_components) == 0:
                return height
            for component in self.container.child_components:
                height += component.computed_height + self.margin
            return height

        def add_child(self, component):
            # type: (GUI.Component) -> None
            """Adds a chils component.
            """
            component.position[1] = self.get_cumulative_height()
            component.set_dimensions()
            super(GUI.ListScrollableContainer, self).add_child(component)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            """Removes a child component.
            """
            super(GUI.ListScrollableContainer, self).remove_child(component)
            children_copy = self.container.child_components[:]
            self.container.child_components = []
            for child in children_copy:
                self.add_child(child)

    class TextScrollableContainer(ScrollableContainer):
        """Represents a scrollable container suited for long pieces of text.
        """

        def __init__(self, position, text_component=None, **data):
            # type: (tuple, GUI.ExpandingMultiLineText, ...) -> None
            """TextScrollableContainer instance initializer.
            :param position: the container position
            :param text_component: the text component
            :param data: optional data related to the text scrollable
            """
            # Defaults to creating a text component.
            data["scrollAmount"] = data.get(
                "lineHeight", text_component.line_height if text_component is not None else 16)
            super(GUI.TextScrollableContainer, self).__init__(position, **data)
            if text_component is None:
                self.text_component = GUI.ExpandingMultiLineText((0, 0), "",
                                                                 state.color_palette.get_color(GUI.Palette.item),
                                                                 width=self.container.computed_width,
                                                                 height=self.container.computed_height, scroller=self)
            else:
                self.text_component = text_component
                if self.text_component.computed_width == self.computed_width:
                    self.text_component.width = self.container.width
                    self.text_component.refresh()
            self.add_child(self.text_component)

        def get_text_component(self):
            # type: () -> Union[GUI.ExpandingMultiLineText, GUI.MultiLineEntryField]
            return self.text_component

    class MultiLineTextEntryField(ListScrollableContainer):
        """Represents a multiline text field the behaves like a list scrollable.
        """

        def __init__(self, position, initial_text="", **data):
            # type: (tuple, str, ...) -> None
            """MultiLineTextEntryField instance initializer.
            :param position: the entry field position
            :param initial_text: the initial contents
            :param data: optional data related to the entry field.
            """
            if "border" not in data:
                data["border"] = 1
                data["borderColor"] = state.color_palette.get_color(GUI.Palette.accent)
            data[GUI.CompEvt.on_click] = self.activate_last
            data[GUI.CompEvtData.on_click_data] = ()
            super(GUI.MultiLineTextEntryField, self).__init__(position, **data)
            self.line_height = data.get("lineHeight", 20)
            self.max_lines = data.get("maxLines", -2)
            self.background_color = data.get("backgroundColor", state.color_palette.get_color(GUI.Palette.background))
            self.text_color = data.get("color", state.color_palette.get_color(GUI.Palette.item))
            self.text_fields = []
            self.wrapped_lines = []
            self.current_field = -1
            self.set_text(initial_text)

        def activate_last(self):
            # type: () -> None
            self.current_field = len(self.text_fields) - 1
            self.text_fields[self.current_field].activate()

        def refresh(self, children=False):
            # type: (bool) -> None
            """Updates the text entry.
            """
            super(GUI.MultiLineTextEntryField, self).refresh()
            self.clear_children()
            for tf in self.text_fields:
                self.add_child(tf)

        def set_current(self, field):
            # type: (GUI.TextEntryField) -> None
            """Sets the current text entry field.
            """
            self.current_field = self.text_fields.index(field)

        def add_field(self, initial_text):
            # type: (str) -> None
            """Adds an entry field with initial text
            """
            if len(self.text_fields) == self.max_lines:
                return
            field = GUI.TextEntryField((0, 0), initial_text, width=self.container.computed_width,
                                       height=self.line_height,
                                       backgroundColor=self.background_color, textColor=self.text_color)
            field.border = 0
            field.MULTILINE = self
            self.current_field += 1
            self.text_fields.insert(self.current_field, field)
            field.activate()
            self.refresh()

        #         def prependToNextField(self, text): #HOLD FOR NEXT RELEASE
        #             print "Prep: "+text
        #             self.currentField += 1
        #             currentText = self.textFields[self.currentField].textComponent.text
        #             self.textFields[self.currentField].textComponent.text = ""
        #             self.textFields[self.currentField].indicatorPosition = 0
        #             self.textFields[self.currentField].refresh()
        #             self.textFields[self.currentField].activate()
        #             for word in (" "+text+" "+currentText).split(" "):
        #                 self.textFields[self.currentField].appendChar(word+" ")
        #             self.textFields[self.currentField].refresh()

        def remove_field(self, field):
            # type: (GUI.TextEntryField) -> None
            """Removes an entry field.
            """
            if self.current_field > 0:
                if self.text_fields.index(field) == self.current_field:
                    self.current_field -= 1
                self.text_fields.remove(field)
            self.refresh()

        def get_delete_char(self):
            # type: () -> str
            """Deletes a characted at caret's right side.
            """
            cur_field = self.current_field
            nxt_field = cur_field + 1
            if cur_field < len(self.text_fields) - 1:
                c = ""
                try:
                    c = self.text_fields[nxt_field].text_component.text[0]
                    self.text_fields[nxt_field].text_component.text = self.text_fields[nxt_field].textComponent.text[1:]
                    self.text_fields[nxt_field].update_overflow()
                    self.text_fields[nxt_field].refresh()
                except COMMON_EXCEPTIONS:
                    self.remove_field(self.text_fields[nxt_field])
                return c
            return ""

        def get_text(self):
            # type: () -> str
            """Returns the component's text.
            """
            t = ""
            p = 0
            for ftext in [f.getText() for f in self.text_fields]:
                if p in self.wrapped_lines:
                    t += ftext
                else:
                    t += ftext + "\n"
                p += 1
            t.rstrip("\n")
            return t

        def clear(self):
            # type: () -> None
            """Clears the contents.
            """
            del self.text_fields[:]
            del self.wrapped_lines[:]
            self.current_field = -1
            self.refresh()

        def set_text(self, text):
            # type: (str) -> None
            """Sets the component's contents.
            """
            self.clear()
            if text == "":
                self.add_field("")
            else:
                for line in text.replace("\r", "").split("\n"):
                    self.add_field("")
                    line = line.rstrip()
                    words = line.split(" ")
                    old_n = self.current_field
                    for word in words:
                        self.text_fields[self.current_field].append_char(word)
                        self.text_fields[self.current_field].append_char(" ")
                    if old_n != self.current_field:
                        for n in range(old_n, self.current_field):
                            self.wrapped_lines.append(n)
                for field in self.text_fields:
                    if field.overflow > 0:
                        field.textComponent.set_text(field.textComponent.text.rstrip(" "))
                        field.updateOverflow()
            self.refresh()
            state.keyboard.deactivate()

    class FunctionBar(object):
        """The Python OS task bar
        """

        def __init__(self):
            # type: () -> None
            """FunctionBar instance initializer.
            """
            self.container = GUI.Container((0, state.gui.height - 40),
                                           background=state.color_palette.get_color(GUI.Palette.background),
                                           width=state.gui.width, height=40)
            self.launcher_app = state.application_list.get_app("launcher")
            self.notification_menu = GUI.NotificationMenu()
            self.recent_app_switcher = GUI.RecentAppSwitcher()
            self.menu_button = GUI.Image((0, 0), surface=state.icons.get_loaded_icon("menu"),
                                         onClick=self.activate_launcher, onLongClick=Application.full_close_current)
            self.app_title_text = GUI.Text((42, 8), "Python OS 6", state.color_palette.get_color(GUI.Palette.item), 20,
                                           onClick=self.toggle_recent_app_switcher)
            self.clock_text = GUI.Text((state.gui.width - 45, 8), self.format_time(),
                                       state.color_palette.get_color(GUI.Palette.accent), 20,
                                       onClick=self.toggle_notification_menu,
                                       onLongClick=State.rescue)  # Add Onclick Menu
            self.container.add_child(self.menu_button)
            self.container.add_child(self.app_title_text)
            self.container.add_child(self.clock_text)

        def format_time(self):
            # type: () -> str
            """Returns a time stamp in H:MM format.
            """
            time = datetime.now()
            stamp = "{}:{:02}".format(time.hour, time.minute)
            return stamp
            # time = str(datetime.now())
            # if time.startswith("0"): time = time[1:]
            # return time[time.find(" ") + 1:time.find(":", time.find(":") + 1)]

        def render(self):
            # type: () -> None
            """Renders the funtion bar.
            """
            if state.notification_queue.new:
                self.clock_text.color = (255, 59, 59)
            self.clock_text.text = self.format_time()
            self.clock_text.refresh()
            self.container.render(screen)

        def activate_launcher(self):
            # type: () -> None
            """Shows the application laucher.
            """
            if state.active_application is not self.launcher_app:
                self.launcher_app.activate()
            else:
                Application.full_close_current()

        def toggle_notification_menu(self):
            # type: () -> None
            """Shows or hides the notification menu.
            """
            if self.notification_menu.displayed:
                self.notification_menu.hide()
            else:
                self.notification_menu.display()

        def toggle_recent_app_switcher(self):
            # type: () -> None
            """Shows or hides the application switcher
            """
            if self.recent_app_switcher.displayed:
                self.recent_app_switcher.hide()
            else:
                self.recent_app_switcher.display()

    class Keyboard(object):
        """Represents the input method editor.
        """

        def __init__(self, text_entry_field=None):
            # type: (GUI.TextEntryField) -> None
            """Keyboard instance initializer.
            :param text_entry_field: the text field to receive keyboard input.
            """
            self.shift_up = False
            self.active = False
            self.text_entry_field = text_entry_field
            self.moved_ui = False
            self._symbol_font = GUI.Font("res/symbols.ttf", 10, 20)
            if self.text_entry_field.computed_position[1] + self.text_entry_field.computed_height > 2 * (
                        state.gui.height / 3) or self.text_entry_field.data.get("slideUp", False):
                state.active_application.ui.set_position((0, -80))
                self.moved_ui = True
            self.base_container = GUI.Container((0, 0), width=state.gui.width, height=state.gui.height / 3)
            self.base_container.set_position((0, 2 * (state.gui.height / 3)))
            self.key_width = self.base_container.computed_width / 10
            self.key_height = self.base_container.computed_height / 4
            use_ft = state.typing_font.freetype is not False
            # if use_ft:
            self.shift_sym = u"⇧"
            self.enter_sym = u"⏎"
            self.bkspc_sym = u"⌫"
            self.delet_sym = u"⌦"
            #             else:
            #                 self.shift_sym = "sh"
            #                 self.enter_sym = "->"
            #                 self.bkspc_sym = "<-"
            #                 self.delet_sym = "del"
            self.keys1 = [["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
                          ["a", "s", "d", "f", "g", "h", "j", "k", "l", self.enter_sym],
                          [self.shift_sym, "z", "x", "c", "v", "b", "n", "m", ",", "."],
                          ["!", "?", " ", "", "", "", "", "-", "'", self.bkspc_sym]]
            self.keys2 = [["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                          ["@", "#", "$", "%", "^", "&", "*", "(", ")", "_"],
                          ["=", "+", "\\", "/", "<", ">", "|", "[", "]", ":"],
                          [";", "{", "}", "", "", "", "", "-", "\"", self.delet_sym]]
            row = 0
            for symrow in self.keys1:
                sym = 0
                for symbol in symrow:
                    if symbol == "":
                        sym += 1
                        continue
                    if symbol == " ":
                        button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height), "",
                                                    self.keys2[row][sym],
                                                    onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                    onLongClick=self.insert_char,
                                                    onLongClickData=(self.keys2[row][sym],),
                                                    width=self.key_width * 5, height=self.key_height, freetype=use_ft)
                    else:
                        if (symbol == self.shift_sym or symbol == self.enter_sym or symbol == self.bkspc_sym or
                                symbol == self.delet_sym):
                            button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height),
                                                        self.keys1[row][sym], self.keys2[row][sym],
                                                        onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                        onLongClick=self.insert_char,
                                                        onLongClickData=(self.keys2[row][sym],),
                                                        width=self.key_width, height=self.key_height, border=1,
                                                        borderColor=state.color_palette.get_color(GUI.Palette.accent),
                                                        font=self._symbol_font, freetype=use_ft)
                        else:
                            button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height),
                                                        self.keys1[row][sym], self.keys2[row][sym],
                                                        onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                        onLongClick=self.insert_char,
                                                        onLongClickData=(self.keys2[row][sym],),
                                                        width=self.key_width, height=self.key_height,
                                                        freetype=use_ft)
                    self.base_container.add_child(button)
                    sym += 1
                row += 1

        def deactivate(self):
            # type: () -> None
            """Deactivates the keyboard.
            """
            self.active = False
            if self.moved_ui:
                state.active_application.ui.position[1] = 0
            self.text_entry_field = None

        def set_text_entry_field(self, field):
            # type: (GUI.TextEntryField) -> None
            """Sets the entry field to receive input.
            """
            self.text_entry_field = field
            self.active = True
            if (self.text_entry_field.computed_position[1] + self.text_entry_field.height >
                    state.gui.height - self.base_container.computed_height or
                    self.text_entry_field.data.get("slideUp", False)):
                state.active_application.ui.set_position((0, -self.base_container.computed_height))
                self.moved_ui = True

        def get_entered_text(self):
            # type: () -> str
            """Returns the text of the current entry field receiving input.
            """
            return self.text_entry_field.get_text()

        def insert_char(self, char):
            # type: (str) -> None
            """Inserts a character in the current entry field.
            """
            if char == self.shift_sym:
                self.shift_up = not self.shift_up
                for button in self.base_container.child_components:
                    if self.shift_up:
                        button.primary_text_component.text = button.primary_text_component.text.upper()
                    else:
                        button.primary_text_component.text = button.primary_text_component.text.lower()
                    button.primary_text_component.refresh()

            elif char == self.enter_sym:
                mult = self.text_entry_field.MULTILINE
                self.deactivate()
                if mult is not None:
                    mult.text_fields[mult.currentField].do_blink = False
                    mult.add_field("")

            elif char == self.bkspc_sym:
                self.text_entry_field.backspace()

            elif char == self.delet_sym:
                self.text_entry_field.delete()

            else:
                if self.shift_up:
                    self.text_entry_field.append_char(char.upper())
                    self.shift_up = False
                    for button in self.base_container.child_components:
                        button.primary_text_component.text = button.primary_text_component.text.lower()
                        button.primary_text_component.refresh()
                else:
                    self.text_entry_field.append_char(char)

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the keyboard
            """
            self.base_container.render(larger_surface)

    class Overlay(object):
        """Represents a top-most dialog box.
        """
        def __init__(self, position, **data):
            # type: tuple, ...) -> None
            """Overlay instance initlalizer.
            :param position: the overlay position.
            :param data: optional data related to the overlay.
            """
            self.position = list(position)
            self.displayed = False
            self.width = int(
                int(data.get("width").rstrip("%")) * (state.active_application.ui.width / 100.0)) if isinstance(
                data.get("width"), str) else data.get("width", state.gui.width)
            self.height = int(
                int(data.get("height").rstrip("%")) * (state.active_application.ui.height / 100.0)) if isinstance(
                data.get("height"), str) else data.get("height", state.gui.height - 40)
            self.color = data.get("color", state.color_palette.get_color(GUI.Palette.background))
            self.base_container = GUI.Container((0, 0), width=state.gui.width,
                                                height=state.active_application.ui.height, color=(0, 0, 0, 0),
                                                onClick=self.hide)
            self.container = data.get("container", GUI.Container(self.position[:], width=self.width, height=self.height,
                                                                 color=self.color))
            self.base_container.add_child(self.container)
            self.application = state.active_application

        def display(self):
            # type: () -> None
            """Shows the overlay
            """
            self.application = state.active_application
            self.application.ui.set_dialog(self)
            self.displayed = True

        def hide(self):
            # type: () -> None
            """Hides the overlay
            """
            self.application.ui.clear_dialog()
            self.application.ui.refresh()
            self.displayed = False

        def add_child(self, child):
            # type: (GUI.Component) -> None
            """Adds a child to the overlay container.
            """
            self.container.add_child(child)

    class Dialog(Overlay):
        """Represents a dialog window.
        """
        def __init__(self, title, text, action_buttons, on_response_recorded=None, on_response_recorded_data=(),
                     **data):
            # type: (str, str, tuple list) -> None
            """Dialog instance initializer.
            :param title: the dialog caption
            :param text: the dialog message
            :param action_buttons: the buttons (yes/no, ok/cancel, etc) of the dialog
            :param on_response_recorded: action to perform when pressing a button
            :param on_response_recorded_data: data related to the action perfomed
            :param data: optional data related to the dialog.
            """
            super(GUI.Dialog, self).__init__((0, (state.active_application.ui.height / 2) - 65),
                                             height=data.get("height", 130),
                                             width=data.get("width", state.gui.width),
                                             color=data.get("color",
                                                            state.color_palette.get_color(GUI.Palette.background)))
            self.container.border = 3
            self.container.border_color = state.color_palette.get_color(GUI.Palette.item)
            self.container.refresh()
            self.application = state.active_application
            self.title = title
            self.text = text
            self.response = None
            self.button_list = GUI.Dialog.get_button_list(action_buttons, self) if isinstance(
                action_buttons[0], str) else action_buttons
            self.text_component = GUI.MultiLineText((2, 2), self.text, state.color_palette.get_color(GUI.Palette.item),
                                                    16,
                                                    width=self.container.computed_width - 4, height=96)
            self.button_row = GUI.ButtonRow((0, 96), width=state.gui.width, height=40, color=(0, 0, 0, 0),
                                            padding=0, margin=0)
            for button in self.button_list:
                self.button_row.add_child(button)
            self.add_child(self.text_component)
            self.add_child(self.button_row)
            self.on_response_recorded = on_response_recorded
            self.on_response_recorded_data = on_response_recorded_data

        def display(self):
            # type: () -> None
            """Pops up the dialog.
            """
            state.function_bar.app_title_text.set_text(self.title)
            self.application.ui.set_dialog(self)

        def hide(self):
            # type: () -> None
            """Hides the dialog.
            """
            state.function_bar.app_title_text.set_text(state.active_application.title)
            self.application.ui.clear_dialog()
            self.application.ui.refresh()

        def record_response(self, response):
            # type: (Any) -> None
            """Records and processes the response.
            """
            self.response = response
            self.hide()
            if self.on_response_recorded is not None:
                if self.on_response_recorded_data is not None:
                    self.on_response_recorded(*(self.on_response_recorded_data, self.response))

        def get_response(self):
            """Returns the recorded response.
            """
            # type: () -> Any
            return self.response

        @staticmethod
        def get_button_list(titles, dialog):
            # type: (str, GUI.Dialog) -> list
            """Creates a list of buttons, one for each title in titles.
            :param titles: the sequence of button titles
            :param dialog: the dialog the buttons belong to
            """
            return [GUI.Button((0, 0), title, state.color_palette.get_color(GUI.Palette.item),
                               state.color_palette.get_color(GUI.Palette.background), 18,
                               width=dialog.container.computed_width / len(titles), height=40,
                               onClick=dialog.record_response, onClickData=(title,)) for title in titles]

    class OKDialog(Dialog):
        """Represents a dialog with a single OK response.
        """

        # NOTE: changed in 1.01 - Removed onResponseRecordedData unused parameter.
        def __init__(self, title, text, on_respose_recorded=None):
            # type: (str, str, Callable, Union[tuple, list]) -> None
            """OKDialog instance initializer.
            :param title: the dialog caption
            :param text: the dialog message
            :param on_respose_recorded: the action to perform when pressed a response button
            """
            okbtn = GUI.Button((0, 0), "OK", state.color_palette.get_color(GUI.Palette.item),
                               state.color_palette.get_color(GUI.Palette.background), 18,
                               width=state.gui.width, height=40, onClick=self.record_response, onClickData=("OK",))
            super(GUI.OKDialog, self).__init__(title, text, [okbtn], on_respose_recorded)

    class ErrorDialog(Dialog):
        """Represents a dialog with an error message.
        """
        # NOTE: changed in 1.01 - Removed onResponseRecordedData unused parameter.
        def __init__(self, text, on_respose_recorded=None):
            # type: (str, str, Callable, Union[tuple, list]) -> None
            """ErrorDialog instance initializer.
            :param text: the dialog error message
            :param on_respose_recorded: the action to perform when pressed a response button
            """
            okbtn = GUI.Button((0, 0), "Acknowledged", state.color_palette.get_color(GUI.Palette.item),
                               state.color_palette.get_color(GUI.Palette.background), 18,
                               width=state.gui.width, height=40, onClick=self.record_response,
                               onClickData=("Acknowledged",))
            super(GUI.ErrorDialog, self).__init__("Error", text, [okbtn], on_respose_recorded)
            self.container.background_color = state.color_palette.get_color(GUI.Palette.error)

    class WarningDialog(Dialog):
        """Represents a dialog with a warning message.
        """
        # NOTE: changed in 1.01 - Removed onResponseRecordedData unused parameter.
        def __init__(self, text, on_response_recorded=None):
            # type: (str, Callable, Union[tuple, list]) -> None
            """WarningDialog instance initializer.
            :param text: the dialog message
            :param on_response_recorded: the action to perform when pressed a response button
            """
            okbtn = GUI.Button((0, 0), "OK", state.color_palette.get_color(GUI.Palette.item),
                               state.color_palette.get_color(GUI.Palette.background), 18,
                               width=state.gui.width, height=40, onClick=self.record_response, onClickData=("OK",))
            super(GUI.WarningDialog, self).__init__("Warning", text, [okbtn], on_response_recorded)
            self.container.background_color = state.color_palette.get_color(GUI.Palette.warning)

    class YNDialog(Dialog):
        """Represents a dialog with Yes/No responses.
        """
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            # type: (str, str, Callable, Union[tuple, list]) -> None
            """YNDialog instance initializer.
            :param title: the dialog caption
            :param text: the dialog message
            :param on_response_recorded: the action to perform when pressed a response button
            :param on_response_recorded_data: data related to the dialog responses
            """
            ybtn = GUI.Button((0, 0), "Yes", (200, 250, 200), (50, 50, 50), 18,
                              width=(state.gui.width / 2), height=40, onClick=self.record_response,
                              onClickData=("Yes",))
            nbtn = GUI.Button((0, 0), "No", state.color_palette.get_color(GUI.Palette.item),
                              state.color_palette.get_color(GUI.Palette.background), 18,
                              width=(state.gui.width / 2), height=40, onClick=self.record_response,
                              onClickData=("No",))
            super(GUI.YNDialog, self).__init__(title, text, [ybtn, nbtn], on_response_recorded)
            self.onResponseRecordedData = on_response_recorded_data

    class OKCancelDialog(Dialog):
        """Represents a dialog with Ok/Cancel responses.
        """
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            # type: (str, str, Callable, Union[tuple, list]) -> None
            """OKDialog instance initializer.
            :param title: the dialog caption
            :param text: the dialog message
            :param on_response_recorded: the action to perform when pressed a response button
            :param on_response_recorded_data: data related to the dialog responses
            """
            okbtn = GUI.Button((0, 0), "OK", state.color_palette.get_color(GUI.Palette.background),
                               state.color_palette.get_color(GUI.Palette.item), 18,
                               width=state.gui.width / 2, height=40, onClick=self.record_response,
                               onClickData=("OK",))
            cancbtn = GUI.Button((0, 0), "Cancel", state.color_palette.get_color(GUI.Palette.item),
                                 state.color_palette.get_color(GUI.Palette.background), 18,
                                 width=state.gui.width / 2, height=40, onClick=self.record_response,
                                 onClickData=("Cancel",))
            super(GUI.OKCancelDialog, self).__init__(title, text, [okbtn, cancbtn], on_response_recorded,
                                                     on_response_recorded_data)

    class AskDialog(Dialog):
        """Represents a dialog that can receive input from the user.
        """
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            # type: (str, str, Callable, Union[tuple, list]) -> None
            """OKDialog instance initializer.
            :param title: the dialog caption
            :param text: the dialog message
            :param on_response_recorded: the action to perform when pressed a response button
            :param on_response_recorded_data: data related to the dialog responses
            """
            okbtn = GUI.Button((0, 0), "OK", state.color_palette.get_color(GUI.Palette.background),
                               state.color_palette.get_color(GUI.Palette.item), 18,
                               width=state.gui.width / 2, height=40, onClick=self.return_recorded_response)
            cancelbtn = GUI.Button((0, 0), "Cancel", state.color_palette.get_color(GUI.Palette.item),
                                   state.color_palette.get_color(GUI.Palette.background), 18,
                                   width=state.gui.width / 2, height=40, onClick=self.record_response,
                                   onClickData=("Cancel",))
            super(GUI.AskDialog, self).__init__(title, text, [okbtn, cancelbtn], on_response_recorded,
                                                on_response_recorded_data)
            self.text_component.computed_height -= 20
            self.text_component.refresh()
            self.text_entry_field = GUI.TextEntryField((0, 80), width=self.container.computed_width, height=20)
            self.container.add_child(self.text_entry_field)

        def return_recorded_response(self):
            # type: () -> str
            """Returns the dialog input text.
            """
            self.record_response(self.text_entry_field.get_text())

    class CustomContentDialog(Dialog):
        """Represents a dialog with custom contents.
        """
        def __init__(self, title, custom_component, action_buttons, on_response_recorded=None, btn_pad=0, btn_margin=5,
                     **data):
            # type: (GUI.Component, Union[str, tuple, list], Callable, int, int, ...) -> None
            """CustomContentDialog instance initializer.
            :param title: the dialog caption
            :param custom_component: the container for this custom dialog
            :param action_buttons: the dialog response buttons titles
            :param on_response_recorded: the action to be perfomed when a response button is pressed
            :param btn_pad: the button padding
            :param btn_margin: the button margin
            :param data: optional data related to the custom dialog.
            """
            # NOTE: Call to superclass missed.
            self.application = state.active_application
            self.title = title
            self.response = None
            self.base_container = GUI.Container((0, 0), width=state.gui.width,
                                                height=state.active_application.ui.height, color=(0, 0, 0, 0.5))
            self.container = custom_component
            self.button_list = GUI.Dialog.get_button_list(action_buttons, self) if type(
                action_buttons[0]) == str else action_buttons
            self.button_row = GUI.ButtonRow((0, self.container.computed_height - 33),
                                            width=self.container.computed_width,
                                            height=40, color=(0, 0, 0, 0), padding=btn_pad, margin=btn_margin)
            for button in self.button_list:
                self.button_row.add_child(button)
            self.container.add_child(self.button_row)
            self.base_container.add_child(self.container)
            self.on_response_recorded = on_response_recorded
            self.data = data
            self.on_response_recorded_data = data.get("onResponseRecordedData", ())

    class NotificationMenu(Overlay):
        """Represents the system's notification menu.
        """
        def __init__(self):
            # type: () -> None
            """NotificationMenu instance initializer.
            """
            super(GUI.NotificationMenu, self).__init__(("20%", "25%"), width="80%", height="75%",
                                                       color=(20, 20, 20, 200))
            self.text = GUI.Text((1, 1), "Notifications", (200, 200, 200), 18)
            self.clear_all_btn = GUI.Button((self.width - 50, 0), "Clear", (200, 200, 200), (20, 20, 20), width=50,
                                            height=20, onClick=self.clear_all)
            self.n_container = GUI.ListScrollableContainer((0, 20), width="80%", height=self.height - 20,
                                                           transparent=True, margin=5)
            self.add_child(self.text)
            self.add_child(self.clear_all_btn)
            self.add_child(self.n_container)
            self.refresh()

        def refresh(self):
            # type: () -> None
            """Updates the notification menu.
            """
            self.n_container.clear_children()
            for notification in state.notification_queue.notifications:
                self.n_container.add_child(notification.getContainer())

        def display(self):
            # type: () -> None
            """Shows the notification menu.
            """
            self.refresh()
            state.notification_queue.new = False
            state.function_bar.clock_text.color = state.color_palette.get_color(GUI.Palette.accent)
            super(GUI.NotificationMenu, self).display()

        def clear_all(self):
            # type: () -> None
            """Removes all notifications from the notification queue.
            """
            state.notification_queue.clear()
            self.refresh()

    class RecentAppSwitcher(Overlay):
        """Represents a menu that allows to switch between application.
        """
        def __init__(self):
            # type: () -> None
            """RecentAppSwitcher instance initializer.
            """
            super(GUI.RecentAppSwitcher, self).__init__((0, screen.get_height() - 100), height=60)
            self.container.border = 1
            self.container.border_color = state.color_palette.get_color(GUI.Palette.item)
            self.recent_pages = None                    # type: GUI.PagedContainer
            self.btn_left = None                        # type: GUI.Button
            self.btn_right = None                       # type: GUI.Button

        def populate(self):
            # type: () -> None
            """Enlists all the recent applications.
            """
            self.container.clear_children()
            self.recent_pages = GUI.PagedContainer((20, 0), width=self.width - 40, height=60, hideControls=True)
            self.recent_pages.add_page(self.recent_pages.generate_page())
            self.btn_left = GUI.Button((0, 0), "<", state.color_palette.get_color(GUI.Palette.accent),
                                       state.color_palette.get_color(GUI.Palette.item), 20, width=20, height=60,
                                       onClick=self.recent_pages.page_left)
            self.btn_right = GUI.Button((self.width - 20, 0), ">", state.color_palette.get_color(GUI.Palette.accent),
                                        state.color_palette.get_color(GUI.Palette.item), 20, width=20, height=60,
                                        onClick=self.recent_pages.page_right)
            per_app = (self.width - 40) / 4
            current = 0
            for app in state.application_list.active_applications:
                if app is not state.active_application and app.parameters.get("persist", True) and app.name != "home":
                    if current >= 4:
                        current = 0
                        self.recent_pages.add_page(self.recent_pages.generate_page())
                    cont = GUI.Container((per_app * current, 0), transparent=True, width=per_app, height=self.height,
                                         border=1, borderColor=state.color_palette.get_color(GUI.Palette.item),
                                         onClick=self.activate, onClickData=(app,), onLongClick=self.close_ask,
                                         onLongClickData=(app,))
                    cont.SKIP_CHILD_CHECK = True
                    icon = app.getIcon()
                    if not icon:
                        icon = state.icons.get_loaded_icon("unknown")
                    img = GUI.Image((0, 5), surface=icon)
                    img.position[0] = GUI.get_centered_coordinates(img, cont)[0]
                    name = GUI.Text((0, 45), app.title, state.color_palette.get_color(GUI.Palette.item), 10)
                    name.position[0] = GUI.get_centered_coordinates(name, cont)[0]
                    cont.add_child(img)
                    cont.add_child(name)
                    self.recent_pages.add_child(cont)
                    current += 1
            if len(self.recent_pages.get_page(0).child_components) == 0:
                notxt = GUI.Text((0, 0), "No Recent Apps", state.color_palette.get_color(GUI.Palette.item), 16)
                notxt.position = GUI.get_centered_coordinates(notxt, self.recent_pages.get_page(0))
                self.recent_pages.add_child(notxt)
            self.recent_pages.go_to_page()
            self.add_child(self.recent_pages)
            self.add_child(self.btn_left)
            self.add_child(self.btn_right)

        def display(self):
            # type: () -> None
            """Shows the app switcher.
            """
            self.populate()
            super(GUI.RecentAppSwitcher, self).display()

        def activate(self, app):
            # type: () -> None
            """Activates the app switcher
            """
            self.hide()
            app.activate()

        def close_ask(self, app):
            # type: (Application) -> None
            """Pops up a confirmation whether to close the selected application.
            :param app: the application
            """
            GUI.YNDialog("Close", "Are you sure you want to close the app " + app.title + "?", self.close,
                         (app,)).display()

        def close(self, app, resp):
            if resp == "Yes":
                app.deactivate(False)
                self.hide()
                if state.active_application == state.application_list.get_app("launcher"):
                    Application.full_close_current()

    class Selector(Container):
        """?
        """
        def __init__(self, position, items, **data):
            self.on_value_changed = data.get("onValueChanged", Application.dummy)
            self.on_value_changed_data = data.get("onValueChangedData", ())
            self.overlay = GUI.Overlay((20, 20), width=state.gui.width - 40, height=state.gui.height - 80)
            self.overlay.container.border = 1
            self.scroller = GUI.ListScrollableContainer((0, 0), transparent=True, width=self.overlay.width,
                                                        height=self.overlay.height, scrollAmount=20)
            for comp in self.generate_item_sequence(items, 14, state.color_palette.get_color(GUI.Palette.item)):
                self.scroller.add_child(comp)
            self.overlay.add_child(self.scroller)
            super(GUI.Selector, self).__init__(position, **data)
            self.event_bindings[GUI.CompEvt.on_click] = self.show_overlay
            self.event_data[GUI.CompEvtData.on_click_data] = ()
            self.text_color = data.get("textColor", state.color_palette.get_color(GUI.Palette.item))
            self.items = items
            self.current_item = self.items[0]
            self.text_component = GUI.Text((0, 0), self.current_item, self.text_color, 14, onClick=self.show_overlay)
            self.text_component.set_position([2, GUI.get_centered_coordinates(self.text_component, self)[1]])
            self.add_child(self.text_component)

        def show_overlay(self):
            # type: () -> None
            """Shows the overlay.
            """
            self.overlay.display()

        def generate_item_sequence(self, items, size=22, color=(0, 0, 0)):
            # type: (list, int, tuple) -> list
            comps = []
            acc_height = 0
            for item in items:
                el_c = GUI.Container((0, acc_height), transparent=True, width=self.overlay.width, height=40,
                                     onClick=self.on_select, onClickData=(item,), border=1, borderColor=(20, 20, 20))
                elem = GUI.Text((2, 0), item, color, size,
                                onClick=self.on_select, onClickData=(item,))
                elem.position[1] = GUI.get_centered_coordinates(elem, el_c)[1]
                el_c.add_child(elem)
                el_c.SKIP_CHILD_CHECK = True
                comps.append(el_c)
                acc_height += el_c.computed_height
            return comps

        def on_select(self, new_val):
            # type: (str) -> None
            """
            :param new_val:
            """
            self.overlay.hide()
            self.current_item = new_val
            self.text_component.text = self.current_item
            self.text_component.refresh()
            self.on_value_changed(*(self.on_value_changed_data + (new_val,)))

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            """Renders the overlay.
            """
            super(GUI.Selector, self).render(larger_surface)
            pygame.draw.circle(larger_surface, state.color_palette.get_color(GUI.Palette.accent), (
                self.computed_position[0] + self.computed_width - (self.computed_height / 2) - 2,
                self.computed_position[1] + (self.computed_height / 2)), (self.computed_height / 2) - 5)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> Selector
            """Overrides Container.get_clicked_child()
            """
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        @property
        def get_value(self):
            # type: () -> str
            """Gets the current item.
            """
            return self.current_item


class ImmersionUI(object):
    """Enables full application control over the UI.
    """
    def __init__(self, app):
        # type: (Application) -> None
        """ImmarsionUI instance initializer.
        :param app: the application requesting immersion.
        """
        self.application = app
        self.method = getattr(self.application.module, self.application.parameters["immersive"])
        self.on_exit = None

    def launch(self, resp):
        # type: (bool) -> None
        """Lauches the application in immersive mode if permition was given.
        """
        if resp == "Yes":
            self.method(*(self, screen))
            if self.on_exit is not None:
                self.on_exit()

    def start(self, on_exit=None):
        # type: (Callable) -> None
        """Immersion mode entry point.
        """
        self.on_exit = on_exit
        GUI.YNDialog("Fullscreen",
                     "The application " + self.application.title + " is requesting total control of the UI. Launch?",
                     self.launch).display()


AppEvt = namedtuple("AppEvt", "on_start on_start_real on_start_block on_stop on_pause on_resume on_custom".split())(
    "onStart", "onStartReal", "onStartBlock", "onStop", "onPause", "onResume", "onCustom")


class Application(object):
    """Represents a Python OS application.
    """

    @staticmethod
    def dummy(*args, **kwargs):
        # type: (...) -> None
        """An empty default handler.
        """
        pass

    @staticmethod
    def get_listings():
        # type: () -> dict
        """Returns the system's installed applications.
        """
        return read_json("apps/apps.json", {})

    @staticmethod
    def chain_refresh_current():
        # type: () -> None
        """Updates the current active application.
        """
        if state.active_application is not None:
            state.active_application.chain_refresh()

    @staticmethod
    def set_active_app(app="prev"):
        # type: (str) -> None
        """Sets an application as currently active.
        """
        if app == "prev":
            app = state.application_list.most_recent_active
        state.active_application = app
        state.function_bar.app_title_text.set_text(state.active_application.title)
        state.gui.repaint()
        state.application_list.push_active_app(app)

    @staticmethod
    def full_close_app(app):
        # type: (Application) -> None
        """Fully closes the given active application.
        """
        app.deactivate(False)
        state.application_list.most_recent_active.activate(fromFullClose=True)

    @staticmethod
    def full_close_current():
        # type: () -> None
        """Fully closes the current active application.
        """
        if state.active_application.name != "home":
            Application.full_close_app(state.active_application)

    @staticmethod
    def remove_listing(location):
        # type: (str) -> None
        """Removes an application from the system's list of apps.
        """
        alist = Application.get_listings()
        try:
            del alist[location]
        except COMMON_EXCEPTIONS:
            print("The application listing for {} could not be removed.".format(location))

        with open("apps/apps.json", "w") as listingsfile:
            json.dump(alist, listingsfile)

    @staticmethod
    def install(packageloc):
        # type: (str) -> str
        """Installs an application from a given package.
        """
        with ZipFile(packageloc, "r") as package:
            package.extract("app.json", "temp/")
            app_info = read_json("temp/app.json")
            app_name = str(app_info.get("name"))
            if app_name not in state.application_list.applications.keys():
                os.mkdir(os.path.join("apps/", app_name))
            else:
                print("Upgrading {}".format(app_name))
            package.extractall(os.path.join("apps/", app_name))

        alist = Application.get_listings()
        alist[os.path.join("apps/", app_name)] = app_name

        with open("apps/apps.json", "w") as listingsfile:
            json.dump(alist, listingsfile)

        return app_name

    @staticmethod
    def register_debug_app_ask():
        # type: () -> None
        """Registers the application (at given location) on the system.
        """
        state.application_list.get_app("files").module.FolderPicker((10, 10), width=220, height=260,
                                                                    onSelect=Application.register_debug_app,
                                                                    startFolder="apps/").display()

    @staticmethod
    def register_debug_app(path):
        # type: (str) -> None
        """Registers the application on the system.
        """
        app_info = read_json(os.path.join(path, "app.json"))
        app_name = str(app_info.get("name"))
        alist = Application.get_listings()
        alist[os.path.join("apps/", app_name)] = app_name

        with open("apps/apps.json", "w") as listingsfile:
            json.dump(alist, listingsfile)

        state.application_list.reload_list()
        GUI.OKDialog("Registered",
                     "The application from {} has been registered on the system.".format(path)).display()

    def __init__(self, location):
        # type: (str) -> None
        """Application instance initializer.
        :param location: the app's directory.
        """
        self.parameters = {}
        self.location = location
        app_data = read_json(os.path.join(location, "app.json").replace("\\", "/"))
        self.name = str(app_data.get("name"))
        self.title = str(app_data.get("title", self.name))
        self.version = float(app_data.get("version", 0.0))
        self.author = str(app_data.get("author", "No Author"))
        self._module = apps.import_app_module(app_data.get("module", self.name))
        # self._module = import_module("apps.{}".format(app_data.get("module", self.name)), "apps")     # type: ModuleType
        self._module.state = state
        self.file = None

        self.main_method = getattr(self._module, str(app_data.get("main")), Application.dummy)

        if "more" in app_data:
            self.parameters = app_data.get("more")

        self.description = app_data.get("description", "No Description.")

        # Immersion check
        if "immersive" in self.parameters:
            self.immersion_ui = ImmersionUI(self)
        else:
            self.immersion_ui = None

        # check for and load event handlers
        self.evt_handlers = {}
        for app_event in AppEvt:
            if app_event in self.parameters:
                self.evt_handlers[app_event] = getattr(self._module, self.parameters[app_event])

        self.thread = Thread(self.main_method, **self.evt_handlers)
        self.ui = GUI.AppContainer(self)
        self.dataStore = DataStore(self)
        self.thread = Thread(self.main_method, **self.evt_handlers)

    @property
    def module(self):
        # type: () -> ModuleType
        """Gets the application module.
        """
        return self._module

    def chain_refresh(self):
        # type: () -> None
        """Updates the application interface.
        """
        self.ui.refresh()

    def on_start(self):
        # type: () -> None
        """Called when..."""
        self.load_color_scheme()
        if AppEvt.on_start_real in self.evt_handlers and not self.evt_handlers.get(AppEvt.on_start_block, False):
            getattr(self._module, self.evt_handlers[AppEvt.on_start_real])(state, self)
        if self.evt_handlers.get(AppEvt.on_start_block, False):
            self.evt_handlers[AppEvt.on_start_block] = False

    def load_color_scheme(self):
        # type: () -> None
        """Loads the application color scheme.
        """
        if "colorScheme" in self.parameters:
            state.color_palette.scheme = self.parameters["colorScheme"]
        else:
            state.color_palette.scheme = GUI.Scheme.normal
        self.ui.background_color = state.color_palette.get_color(GUI.Palette.background)
        self.ui.refresh()

    def activate(self, **data):
        # type: (...) -> None
        """Starts the application up.
        """
        try:
            if data.get("noOnStart", False):
                self.evt_handlers[AppEvt.on_start_block] = True
            if state.active_application is self:
                return
            if state.application_list.most_recent_active is not None and not data.get("fromFullClose", False):
                state.application_list.most_recent_active.deactivate()
            Application.set_active_app(self)
            self.load_color_scheme()

            if self.thread in state.thread_controller.threads:
                self.thread.set_pause(False)
            else:
                if self.thread.stop:
                    self.thread = Thread(self.main_method, **self.evt_handlers)
                state.thread_controller.add_thread(self.thread)
        except COMMON_EXCEPTIONS:
            State.error_recovery("Application init error.", "App name: " + self.name)

    # NOTE: new in 1.01 - getIcon() turned into a property
    @property
    def icon(self):
        # type: () -> pygame.Surface
        if "icon" in self.parameters:
            if self.parameters["icon"] is None:
                return False
            return state.icons.get_loaded_icon(self.parameters["icon"], self.location)
        else:
            return state.icons.get_loaded_icon("unknown")

    def deactivate(self, pause=True):
        # type: (bool) -> None
        """Suspends or closes the application.
        """
        if "persist" in self.parameters:
            if self.parameters["persist"] is False:
                pause = False
        if pause:
            self.thread.set_pause(True)
        else:
            self.ui.clear_children()
            self.thread.set_stop()
            state.application_list.close_app(self)
        state.color_palette.scheme = GUI.Scheme.normal

    def uninstall(self):
        # type: () -> None
        """Uninstalls the application.
        """
        rmtree(self.location, True)
        Application.remove_listing(self.location)


class ApplicationList(object):
    """Represents the list of all applications installed in the system.
    """

    def __init__(self):
        # type: () -> None
        """ApplicationList instance initializer.
        """
        self.applications = {}
        self.active_applications = []
        applist = Application.get_listings().copy()
        for key in applist:
            try:
                self.applications[applist.get(key)] = Application(key)
            except COMMON_EXCEPTIONS:
                State.error_recovery("App init error: " + key, "NoAppDump")

    def get_app(self, name):
        # type: (str) -> Application
        """Returns the corresponding application by its name, if it is in the list; None, otherwise.
        """
        return self.applications.get(name)

    # NOTE: new in 1.01 - getApplicationList() turned into a property.
    @property
    def application_list(self):
        # type: () -> list
        """Returns a list of applications.
        """
        return self.applications.values()

    def push_active_app(self, app):
        # type: (Application) -> None
        """Pushes the given application to the list of active applications.
        """
        if app not in self.active_applications:
            self.active_applications.insert(0, app)
        else:
            self.switch_last(app)

    def close_app(self, app=None):
        # type: (Application) -> Application
        """Closes an application, the currently active or an specific app.
        """
        if app is None:
            if len(self.active_applications) != 0:
                return self.active_applications.pop(0)
        self.active_applications.remove(app)

    def switch_last(self, app):
        # type: (Application) ->  None
        """Moves the given application to the beginning (or front) of the list.
        """
        if app is None:
            return
        index = self.active_applications.index(app)
        application = self.active_applications.pop(index)                       # type: Application
        self.active_applications.insert(0, application)

    # NOTE: new in 1.01 - getMostRecentActive() turned into a property
    @property
    def most_recent_active(self):
        # type: () -> Application
        """Returns the most recently active application.
        """
        if len(self.active_applications) > 0:
            return self.active_applications[0]
        return None

    # NOTE: new in 1.01 - getMostPreviousActive() turned into a property
    @property
    def previous_active(self):
        # type: () -> Application
        """Returns the second most recently active application.
        """
        if len(self.active_applications) > 1:
            return self.active_applications[1]

    def reload_list(self):
        # type: () -> None
        """Reloads and updates the list of applications.
        """
        applist = Application.get_listings()
        for key in dict(applist).keys():
            if applist.get(key) not in self.applications.keys():
                try:
                    self.applications[applist.get(key)] = Application(key)
                except COMMON_EXCEPTIONS:
                    State.error_recovery("App init error: " + key, "NoAppDump")
        for key in self.applications.keys():
            if key not in applist.values():
                del self.applications[key]


class Notification(object):
    """Represents a system or application notification message
    """

    def __init__(self, title, text, **data):
        # type: (str, str, ...) -> None
        """Notification instance initializer.
        :param title: the notification title
        :param text: the notification message
        :param data: optional data related to the notification
        """
        self.title = title
        self.text = text
        self.active = True
        self.source = data.get("source", None)
        self.image = data.get("image", None)
        if self.source is not None:
            self.on_selected_method = data.get("onSelected", self.source.activate)
        else:
            self.on_selected_method = data.get("onSelected", Application.dummy)
        self.on_selected_data = data.get("onSelectedData", ())

    def on_selected(self):
        # type: () -> None
        """Called when the notification gets selected.
        """
        self.clear()
        state.function_bar.toggle_notification_menu()
        self.on_selected_method(*self.on_selected_data)

    def clear(self):
        # type: () -> None
        """Removes all notifications from the queue.
        """
        self.active = False
        state.notification_queue.sweep()
        state.function_bar.notification_menu.refresh()

    def get_container(self, c_width=200, c_height=40):
        # type: (int, int) -> GUI.Container
        """Creates and returns a container.

        :param c_width: the container width in pixels
        :param c_height: the container height in pixels
        """
        cont = GUI.Container((0, 0), width=c_width, height=c_height, transparent=True, onClick=self.on_selected,
                             onLongClick=self.clear)
        if self.image is not None:
            try:
                self.image.set_position([0, 0])
                cont.add_child(self.image)
            except COMMON_EXCEPTIONS:
                if isinstance(self.image, pygame.Surface):
                    self.image = GUI.Image((0, 0), surface=self.image, onClick=self.on_selected)
                else:
                    self.image = GUI.Image((0, 0), path=self.image, onClick=self.on_selected)
        else:
            self.image = GUI.Image((0, 0), surface=state.icons.get_loaded_icon("unknown"), onClick=self.on_selected,
                                   onLongClick=self.clear)
        rtitle = GUI.Text((41, 0), self.title, (200, 200, 200), 20, onClick=self.on_selected, onLongClick=self.clear)
        rtxt = GUI.Text((41, 24), self.text, (200, 200, 200), 14, onClick=self.on_selected, onLongClick=self.clear)
        cont.add_child(self.image)
        cont.add_child(rtitle)
        cont.add_child(rtxt)
        return cont


class PermanentNotification(Notification):
    """Represents a notification that is not removed through the common mechanism.
    """
    def clear(self):
        # type: () -> None
        pass

    def force_clear(self):
        # type: () -> None
        super(PermanentNotification, self).clear()


class NotificationQueue(object):
    """Represents a queue of notifications.
    """
    def __init__(self):
        # type: () -> None
        """NotificationQueue instance initializer.
        """
        self.notifications = []
        self.new = False

    def sweep(self):
        # type: () -> None
        """Removes all inactive notifications from the queue.
        """
        for notification in self.notifications:
            if not notification.active:
                self.notifications.remove(notification)

    def push(self, notification):
        # type: (Notification) -> None
        """Adds a new notification.
        """
        self.notifications.insert(0, notification)
        self.new = True

    def clear(self):
        # type: () -> None
        """Clears the notification queue.
        """
        del self.notifications[:]       # replace by list.clear() method when in Python34


class DataStore(object):
    """Interface for storing/retrieving data from json files.
    """
    def __init__(self, app):
        # type: (Application) -> None
        """DataStore instance initializer.
        :param app: the application wich the data is associated to.
        """
        self.application = app
        self.ds_path = os.path.join("res/", app.name + ".ds")
        self.data = None                # type: dict

    def get_store(self):
        # type: () -> dict
        """loads data from a json file.
        """
        if not os.path.exists(self.ds_path):
            with open(self.ds_path, "w") as wf:
                json.dump({"dsApp": self.application.name}, wf)

        with open(self.ds_path, "rU") as rf:
            self.data = json.loads(" ".join(rf.readlines()))

        return self.data

    def save_store(self):
        # type: () -> None
        """Saves data to a json file.
        """
        with open(self.ds_path, "w") as wf:
            json.dump(self.data, wf)

    def get(self, key, default=None):
        # type: (str, Any) -> Any
        return self.get_store().get(key, default)

    def set(self, key, value):
        # type: (str, Any) -> None
        self.data[key] = value
        self.save_store()

    def __getitem__(self, itm):
        return self.get(itm)

    def __setitem__(self, key, val):
        self.set(key, val)


class State(object):
    def __init__(self, active_app=None, colors=None, icons=None, controller=None, event_queue=None,
                 notification_queue=None, functionbar=None, font=None, t_font=None, gui=None, app_list=None,
                 keyboard=None):
        # type: (Application, GUI.ColorPalette, GUI.Icons, Controller, GUI.EventQueue, NotificationQueue,
        #  GUI.FunctionBar, GUI.Font, GUI.Font, GUI, ApplicationList, GUI.Keyboard) -> None
        """State instance initializer.
        :param active_app: the active application.
        :param colors: the color theme
        :param icons: the icon resources
        :param controller: the thread controller
        :param event_queue: the queue of events
        :param notification_queue: the queue of notifications
        :param functionbar: the system function bar
        :param font: the font used to render text
        :param t_font: the typing font
        :param gui: que GUI toolkit
        :param app_list: the application list
        :param keyboard: the input method editor
        """
        self._active_application = active_app
        self._color_palette = colors
        self._icons = icons
        self._thread_controller = controller
        self._event_queue = event_queue
        self._notification_queue = notification_queue
        self._function_bar = functionbar
        self._font = font
        self._typing_font = t_font
        self._app_list = app_list
        self._keyboard = keyboard
        self._recent_app_switcher = None
        if gui is None:
            self._gui = GUI()
        if colors is None:
            self._color_palette = GUI.ColorPalette()
        if icons is None:
            self._icons = GUI.Icons()
        if controller is None:
            self._thread_controller = Controller()
        if event_queue is None:
            self._event_queue = GUI.EventQueue()
        if notification_queue is None:
            self._notification_queue = NotificationQueue()
        if font is None:
            self._font = GUI.Font()
        if t_font is None:
            self._typing_font = GUI.Font("res/RobotoMono-Regular.ttf")

    @property
    def active_application(self):
        # type: () -> Application
        """Gets or sets the active application.
        """
        return self._active_application

    @active_application.setter
    def active_application(self, value):
        # type: (Application) -> None
        self._active_application = value

    @property
    def application_list(self):
        # type: () -> ApplicationList
        """Gets or sets the list of applications
        """
        if self._app_list is None:
            self._app_list = ApplicationList()
        return self._app_list

    @application_list.setter
    def application_list(self, value):
        self._app_list = value

    @property
    def color_palette(self):
        # type: () -> GUI.ColorPalette
        """Gets or sets the system color palette"""
        return self._color_palette

    @color_palette.setter
    def color_palette(self, value):
        # type: (GUI.ColorPalette) -> None
        self._color_palette = value

    @property
    def icons(self):
        # type: () -> GUI.Icons
        """Gets or sets the system set of icons
        """
        return self._icons

    @icons.setter
    def icons(self, value):
        # type: (GUI.Icons) -> None
        self._icons = value

    @property
    def thread_controller(self):
        # type: () -> Controller
        """Gets or sets the system's thread controller.
        """
        return self._thread_controller

    @thread_controller.setter
    def thread_controller(self, value):
        # type: (Controller) -> None
        self._thread_controller = value

    @property
    def event_queue(self):
        # type: () -> GUI.EventQueue
        """Gets or sets the system's event queue.
        """
        return self._event_queue

    @event_queue.setter
    def event_queue(self, value):
        # type: (GUI.EventQueue) -> None
        self._event_queue = value

    @property
    def notification_queue(self):
        # type: () -> NotificationQueue
        """Gets or sets the notification queue.
        """
        return self._notification_queue

    @notification_queue.setter
    def notification_queue(self, value):
        # type: (NotificationQueue) -> None
        self._notification_queue = value

    @property
    def font(self):
        # type: () -> GUI.Font
        """Gets or sets the system's font.
        """
        return self._font

    @font.setter
    def font(self, value):
        # type: (GUI.Font) -> None
        """Gets or sets the system's font.
        """
        self._font = value

    @property
    def typing_font(self):
        # type: () -> GUI.Font
        """Gets ro sets the system's typing font.
        """
        return self._typing_font

    @typing_font.setter
    def typing_font(self, value):
        # type: (GUI.Font) -> None
        self._typing_font = value

    @property
    def gui(self):
        # type: () -> GUI
        """Gets or sets the system's UI toolkit
        """
        return self._gui

    @gui.setter
    def gui(self, value):
        # type: (GUI) -> None
        self._gui = value

    @property
    def function_bar(self):
        # type: () -> GUI.FunctionBar
        """Gets or sets the system's function bar.
        """
        if self._function_bar is None:
            self._function_bar = GUI.FunctionBar()
        return self._function_bar

    @function_bar.setter
    def function_bar(self, value):
        # type: (GUI.FunctionBar) -> None
        self._function_bar = value

    @property
    def keyboard(self):
        # type: () -> GUI.Keyboard
        """Gets or sets the system's input method editor.
        """
        return self._keyboard

    @keyboard.setter
    def keyboard(self, value):
        # type: (GUI.Keyboard) -> None
        self._keyboard = value

    @staticmethod
    def get_state():
        # type: () -> State
        """Returns the Python OS system state.
        """
        return state

    @staticmethod
    def exit():
        state.thread_controller.stop_all_threads()
        pygame.quit()
        # NOTE: changed in 1.01 - relace os._exit() by sys.exit()
        sys.exit(1)

    @staticmethod
    def rescue():
        global state                        # type: State
        r_fnt = pygame.font.Font(None, 16)
        r_clock = pygame.time.Clock()
        state.notification_queue.clear()
        state.event_queue.clear()
        print("Recovery menu entered.")
        while True:
            r_clock.tick(10)
            screen.fill([0, 0, 0])
            pygame.draw.rect(screen, [200, 200, 200], [0, 0, 280, 80])
            screen.blit(r_fnt.render("Return to Python OS", 1, [20, 20, 20]), [40, 35])
            pygame.draw.rect(screen, [20, 200, 20], [0, 80, 280, 80])
            screen.blit(r_fnt.render("Stop all apps and return", 1, [20, 20, 20]), [40, 115])
            pygame.draw.rect(screen, [20, 20, 200], [0, 160, 280, 80])
            screen.blit(r_fnt.render("Stop current app and return", 1, [20, 20, 20]), [40, 195])
            pygame.draw.rect(screen, [200, 20, 20], [0, 240, 280, 80])
            screen.blit(r_fnt.render("Exit completely", 1, [20, 20, 20]), [40, 275])
            pygame.display.flip()
            for evt in pygame.event.get():
                if evt.type == pygame.QUIT or evt.type == pygame.KEYDOWN and evt.key == pygame.K_ESCAPE:
                    print("Quit signal detected.")
                    try:
                        state.exit()
                    except COMMON_EXCEPTIONS:
                        pygame.quit()
                        exit()
                if evt.type == pygame.MOUSEBUTTONDOWN:
                    if evt.pos[1] >= 80:
                        if evt.pos[1] >= 160:
                            if evt.pos[1] >= 240:
                                print("Exiting.")
                                try:
                                    state.exit()
                                except COMMON_EXCEPTIONS:
                                    pygame.quit()
                                    exit()
                            else:
                                print("Stopping current app")
                                try:
                                    Application.full_close_current()
                                except COMMON_EXCEPTIONS:
                                    print("Regular stop failed!")
                                    Application.set_active_app(state.application_list.get_app("home"))
                                return
                        else:
                            print("Closing all active applications")
                            for a in state.application_list.active_applications:
                                try:
                                    a.deactivate()
                                except COMMON_EXCEPTIONS:
                                    print("The app {} failed to deactivate!".format(
                                        state.application_list.active_applications.remove(a)))
                            state.application_list.get_app("home").activate()
                            return
                    else:
                        print("Returning to Python OS.")
                        return

    @staticmethod
    def error_recovery(message="Unknown", data=None):
        print(message)
        screen.fill([200, 100, 100])
        rf = pygame.font.Font(None, 24)
        sf = pygame.font.Font(None, 18)
        screen.blit(rf.render("Failure detected.", 1, (200, 200, 200)), [20, 20])
        with open("temp/last_error.txt", "w") as logfile:
            error_report = """PythonOS 6 Error Report
            TIME: {}

            Opened Apps: {}
            Message: {}
            Additional Data:
            {}

            Traceback:
            {}
            """.format(
                datetime.now(),
                [app.name for app in
                 state.application_list.active_applications] if data != "NoAppDump" else "Not Yet Initialized",
                message,
                str(data),
                format_exc()
            )
            print(error_report, file=logfile)

        screen.blit(sf.render("Traceback saved.", 1, (200, 200, 200)), [20, 80])
        screen.blit(sf.render("Location: temp/last_error.txt", 1, (200, 200, 200)), [20, 100])
        screen.blit(sf.render("Message:", 1, (200, 200, 200)), [20, 140])
        screen.blit(sf.render(message, 1, (200, 200, 200)), [20, 160])
        pygame.draw.rect(screen, [200, 200, 200], [0, 280, 240, 40])
        screen.blit(sf.render("Return to Python OS", 1, (20, 20, 20)), [20, 292])
        pygame.draw.rect(screen, [50, 50, 50], [0, 240, 240, 40])
        screen.blit(sf.render("Open Recovery Menu", 1, (200, 200, 200)), [20, 252])
        r_clock = pygame.time.Clock()
        pygame.display.flip()
        while True:
            r_clock.tick(10)
            for evt in pygame.event.get():
                if evt.type == pygame.QUIT or evt.type == pygame.KEYDOWN and evt.key == pygame.K_ESCAPE:
                    try:
                        state.exit()
                    except COMMON_EXCEPTIONS:
                        pygame.quit()
                        exit()
                if evt.type == pygame.MOUSEBUTTONDOWN:
                    if evt.pos[1] >= 280:
                        return
                    elif evt.pos[1] >= 240:
                        State.rescue()
                        return

    @staticmethod
    def main():
        while True:
            # Limit FPS
            state.gui.timer.tick(state.gui.update_interval)
            state.gui.monitor_fps()
            # Update event queue
            state.event_queue.check()
            # Refresh main thread controller
            state.thread_controller.run()
            # Paint UI
            if state.active_application is not None:
                try:
                    state.active_application.ui.render()
                except COMMON_EXCEPTIONS:
                    State.error_recovery("UI error.", "FPS: " + str(state.gui.update_interval))
                    Application.full_close_current()
            state.function_bar.render()
            if state.keyboard is not None and state.keyboard.active:
                state.keyboard.render(screen)

            if state.gui.update_interval <= 20:
                pygame.draw.rect(screen, (255, 0, 0), [state.gui.width - 5, state.gui.height - 5, 5, 5])

            state.gui.refresh()
            # Check Events
            latest_event = state.event_queue.latest_complete
            if latest_event is not None:
                clicked_child = None
                if state.keyboard is not None and state.keyboard.active:
                    if latest_event.pos[1] < state.keyboard.base_container.computed_position[1]:
                        if state.active_application.ui.get_clicked_child(
                                latest_event) == state.keyboard.text_entry_field:
                            state.keyboard.text_entry_field.on_click()
                        else:
                            state.keyboard.deactivate()
                        continue
                    clicked_child = state.keyboard.base_container.get_clicked_child(latest_event)
                    if clicked_child is None:
                        clicked_child = state.active_application.ui.get_clicked_child(latest_event)
                        if (state.keyboard.text_entry_field.computed_position == [0, 0] and
                                state.keyboard.text_entry_field.check_click(latest_event)):
                            clicked_child = state.keyboard.text_entry_field
                else:
                    if latest_event.pos[1] < state.gui.height - 40:
                        if state.active_application is not None:
                            clicked_child = state.active_application.ui.get_clicked_child(latest_event)
                    else:
                        clicked_child = state.function_bar.container.get_clicked_child(latest_event)
                if clicked_child is not None:
                    try:
                        if isinstance(latest_event, GUI.LongClickEvent):
                            clicked_child.on_long_click()
                        else:
                            if isinstance(latest_event, GUI.IntermediateUpdateEvent):
                                clicked_child.on_intermediate_update()
                            else:
                                clicked_child.on_click()
                    except COMMON_EXCEPTIONS:
                        State.error_recovery("Event execution error", "Click event: " + str(latest_event))

    @staticmethod
    def state_shell():
        # For debugging purposes only. Do not use in actual code!
        print("Python OS 6 State Shell. Type \"exit\" to quit.")
        user_input = raw_input("S> ")
        while user_input != "exit":
            if not user_input.startswith("state.") and user_input.find("Static") == -1:
                if user_input.startswith("."):
                    user_input = "state" + user_input
                else:
                    user_input = "state." + user_input
            print(eval(user_input, {"state": state, "Static": State}))
            user_input = raw_input("S> ")
        State.exit()


if __name__ == "__main__":
    state = State()
    globals()["state"] = state
    __builtin__.state = state
    # TEST
    # State.state_shell()
    state.application_list.get_app("home").activate()
    try:
        State.main()
    except COMMON_EXCEPTIONS:
        State.error_recovery("Fatal system error.")
