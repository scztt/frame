import sys

import pkg_resources
import os.path
import schedule
import time
import yaml
import logging
import argparse

from PyQt5.QtCore import Qt, QUrl, QRect, QTimer
from PyQt5.QtGui import QIcon, QColor, QPalette
from PyQt5.QtWidgets import (QAction, QApplication, QDesktopWidget, QDialog, QFileDialog,
                             QHBoxLayout, QLabel, QMainWindow, QToolBar, QVBoxLayout, QWidget, QPushButton, QStackedWidget)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaPlaylist, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget


def string_to_job(schedule_str):
    schedule_str = 'schedule.' + str(schedule_str) + '.do(lambda: print())'
    try:
        return eval(schedule_str)
    except Exception:
        import traceback
        logging.error('Error while evaluating schedule string: ' + schedule_str)
        logging.error(traceback.format_exc())
        return None

def protect(self, func, *args, **kwargs):
    try:
        func()
        return True
    except Exception:
        import traceback
        self.logging.error(traceback.format_exc())
        if self.cancel_on_error:
            self.cancel()
        return False


class Event:
    def __init__(self, settings):
        self.running = False
        self.logging = logging
        self.name = settings.get('name')
        self.tags = settings.get('tags', [])
        self.type = settings.get('type')
        self.job = string_to_job(settings.get('schedule'))
        self.cancel_on_error = settings.get('cancel_on_error', False)

        if self.tags:
            self.job.tags(*self.tags)

        self.job.do(self.run)

        self.state = 'uninitialized'

    def initialize(self):
        logging.debug("Initializing task %s" % (self.name))
        if self.state == 'uninitialized':
            if protect(self, self.do_initialize):
                self.state = 'initialized'
        if self.state == 'playing':
            self.stop()

    def do_initialize(self):
        pass

    def run(self):
        logging.debug("Starting task %s" % (self.name))
        if self.state == 'uninitialized':
            self.initialize()
        if self.state == 'running':
            self.stop()
        if self.state == 'initialized':
            if protect(self, self.do_run):
                self.state = 'running'

    def do_run(self):
        pass

    def stop(self):
        logging.debug("Stopping task %s" % (self.name))
        if self.state == 'running':
            if protect(self, self.do_stop):
                self.state = 'initialized'
 
    def do_stop(self):
        pass

    def reset(self):
        self.stop()
        if protect(self, self.do_reset):
            self.state = 'uninitialized'

    def do_reset(self):
        pass

    def cancel(self):
        self.reset()
        self.state = 'cancelled'

class DisplayEvent(Event):
    def __init__(self, frame, settings):
        super().__init__(settings)
        self.frame = frame
        self.widget = frame.create_widget()
        self.widget.setLayout(QVBoxLayout())
        self.widget.layout().setContentsMargins(0, 0, 0, 0)
        self.widget.layout().setSpacing(0)

        self.fullscreen = settings.get('fullscreen', True)
        self.geometry = settings.get('geometry')

        if (self.geometry):
            self.geometry = QRect(self.geometry[0], self.geometry[1], self.geometry[2], self.geometry[3])

    def add_widget(self, widget):
        if self.geometry:
            widget.setParent(self.widget)
            widget.setGeometry(self.geometry)
        else:
            self.widget.layout().addWidget(widget)

    def run(self):
        self.widget.show()
        self.frame.push(self.widget)
        super().run()

    def stop(self):
        self.frame.pop(self.widget)
        super().stop()

class Frame(QStackedWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.null = QWidget()
        self.stack = [self.null]
        self.addWidget(self.null)
        self.set_current()
        self.autoFillBackground()

        palette = self.palette()
        palette.setColor(QPalette.Background, QColor(0, 0, 0))
        self.setPalette(palette)

        self.setGeometry(QRect(0, 0, 400, 400))
        self.showFullScreen()

    def create_widget(self):
        widget = QWidget()
        self.addWidget(widget)
        return widget

    def push(self, widget):
        self.stack.append(widget)
        self.set_current()

    def pop(self, widget):
        try:
            self.stack.remove(widget)
        except Exception:
            pass
        self.set_current()

    def set_current(self):
        self.setCurrentWidget(self.stack[-1])

class PlayVideo(DisplayEvent):
    def __init__(self, frame, settings):
        super().__init__(frame, settings)

        self.url = QUrl(settings.get('url'))
        self.start_time = settings.get('start', 0) * 1000
        self.duration = settings.get('duration')
        self.loop = settings.get('loop', True)
        self.volume = settings.get('volume', 100)
        self.playback_rate = settings.get('playbackRate', 1.0)

    def do_initialize(self):
        self.video = QVideoWidget()
        self.add_widget(self.video)
        self.video.show()

        self.media = QMediaContent(self.url)
        self.playlist = QMediaPlaylist(self.video)
        self.playlist.addMedia(self.media)
        self.playlist.setPlaybackMode(QMediaPlaylist.Loop if self.loop else QMediaPlaylist.Sequential)

        self.player = QMediaPlayer()
        self.player.setVideoOutput(self.video)
        self.player.setVolume(self.volume)
        self.player.setPlaybackRate(self.playback_rate)
    
    def do_run(self):
        self.player.setPlaylist(self.playlist)
        self.player.setPosition(self.start_time)
        self.player.play()

    def do_stop(self):
        self.player.stop()

def create_event(parent, settings):
    event_types = {
        'PlayVideo': PlayVideo
    }
    logging.info("Creating an event: " + str(settings))
    event_class = event_types.get(settings.get('type'))
    event = event_class(parent, settings)
    return event

def load_events(path, events_list):
    settings_file = open(path, 'r')

    try:
        from yaml import Loader, Dumper
        import yaml
        settings = yaml.load(settings_file, Loader=Loader)
        logging.info("Loaded settings: " + str(settings))
    except ImportError:
        import traceback
        logging.error(traceback.format_exc())
        return

    events = settings.get('events')
    frame = Frame(None)
    for name, event in events.items():
        event['name'] = name
        events_list.append(
            create_event(frame, event)
        )

def tick():
    logging.info("Tick")
    schedule.run_pending()

def main():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('settings_yaml', help='Path to a yaml file with settings')
    args = parser.parse_args()

    logging.root.setLevel(logging.DEBUG)

    application = QApplication(sys.argv)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1000)

    events = []
    load_events(args.settings_yaml, events)

    for e in events:
        e.initialize()

    sys.exit(application.exec_())

if __name__ == '__main__':
    main()
