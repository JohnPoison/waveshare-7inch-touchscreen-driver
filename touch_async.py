#!/usr/bin/env python3

import traceback
import struct
import time
import math
import glob
import uinput
import pyudev
import os
import asyncio
import datetime

class Pos():
    x = 0
    y = 0

    def delta(self, other):
        deltaPos = Pos()
        deltaPos.x = other.x - self.x
        deltaPos.y = other.y - self.y

        return deltaPos
        
    def length(self):
        return math.sqrt(self.x**2 + self.y**2)

    def distance(self, other):
        return self.delta(other).length()
    

class Touch:

    def __init__(self, id):
        self._id = id
        self._pos = Pos()
        self._prevPos = Pos()
        self._touchStart = Pos()

    @property
    def id(self):
        return self._id;

    @property
    def pos(self):
        return self._pos;

    @property
    def active(self):
        return self._active;

    def update(self, x, y, active):
        self._prevActive = self._active;
        self._active = active;
        self._prevPos.x = self._pos.x;
        self._prevPos.y = self._pos.y;
        self._pos.x = x;
        self._pos.y = y;
        if active and not self._prevActive:
            #print('Touch started!')
            self._exceededThreshold = False
            self._activationTime = datetime.datetime.now();
            self._touchStart.x = x
            self._touchStart.y = y
        elif active and self.movementSinceTouch() > 40:
            self._exceededThreshold = True
            #print('exceededThreshold')

    def deltaFromPrevPos(self):
        return self._pos.delta(self._prevPos)

    def movementSinceTouch(self):
        return self._touchStart.distance(self._pos)

    def isMoved(self):
        return self._pos.x != self._prevPos.x or self._pos.y != self._prevPos.y;

    def isChanged(self):
        return self.isMoved() or self.isActiveChanged();

    def isActiveChanged(self):
        return self._active != self._prevActive

    def canTreatAsRightBtn(self):
        return not self._exceededThreshold

    def duration(self):
        """touch duration in seconds"""
        if not self.active:
            return 0
        span = (datetime.datetime.now() - self._activationTime)
        return span.total_seconds()

    def __str__(self):
        return 'Touch({}): active: {} isMoved: {} isActiveChanged: {} duration: {}, pos: {},{} prevPos: {},{} rightClick: {}'.format(self.id, self.active, self.isMoved(), self.isActiveChanged(), self.duration(), self.pos.x, self.pos.y, self._prevPos.x, self._prevPos.y, self.canTreatAsRightBtn())

    _activationTime = datetime.datetime.now()

    """Touch type"""
    _prevPos = None
    _pos = None
    _touchStart = None
    
    _active = False
    _prevActive = False
    _exceededThreshold = False

touches = []
rightClick = False
activeTouches = 0
trackRightClick = True


def check_device(thedevice):
    # Currently we don't get a full udev dictionary from the device on
    # Raspberry pi, so we do a hard search for the device vendor/id hex.
    if '0EEF:0005' in (thedevice.get('DEVPATH')):
        print("Device found at: ", thedevice.device_node)
        with open(thedevice.device_node, 'rb') as f:
            print("Opening device and initiating mouse emulation.")
            tasks.clear()
            tasks.append(asyncio.async(read_and_emulate_mouse(f)))
            loop.run_until_complete(asyncio.wait(tasks))
            print("Device async task terminated.")


def updateTouch(touchData, input_device):
    global rightClick
    global activeTouches
    global trackRightClick
    #print('Touch data', touchData)
    touchIdx = touchData[1] - 1; # since numeration goes from 1
    if touchIdx < 0:
        return
    touch = touches[touchIdx]
    touch.update(touchData[2], touchData[3], touchData[0])
    #if touchIdx == 0:
        #print(touch)
        #print(touchData)

    if activeTouches > 1:
        amount = touch.deltaFromPrevPos().y
        #print('wheel amount', amount)
        if abs(amount) > 2:
            #normalize
            amount /= abs(amount)
            #print('wheel norm amount', amount)
            input_device.emit(uinput.REL_WHEEL, int(amount), True)

    if not rightClick and touchIdx == 0 and activeTouches <= 1 and touch.isMoved():
        #print('set mouse to {},{} for touch {}'.format(touch.pos.x, touch.pos.y, touch))
        input_device.emit(uinput.ABS_X, touch.pos.x, False)
        input_device.emit(uinput.ABS_Y, touch.pos.y, True)
        #if not touch.isActiveChanged():
            #print('emitting additional click')
            #input_device.emit_click(uinput.BTN_LEFT, True)

    if touch.isActiveChanged():
        input_device.emit(uinput.BTN_LEFT, touch.active, True)
        rightClick = False
        activeTouches += 1 if touch.active else -1
        #enable when no touches
        trackRightClick |= activeTouches == 0
        #reset if touches exceeded 1
        trackRightClick &= activeTouches <= 1
        #print('active touches', activeTouches)

    elif (  trackRightClick and
            touch.active and 
            not rightClick and 
            touch.canTreatAsRightBtn() and 
            touch.duration() > 1):
        rightClick = True
        input_device.emit(uinput.BTN_LEFT, 0, False)
        input_device.emit(uinput.BTN_RIGHT, 1, False)
        input_device.emit(uinput.BTN_RIGHT, 0, True)
        #print('RIGHT CLICK!')
        


@asyncio.coroutine
def async_read_data(fd, length):
    yield from asyncio.sleep(0)
    return fd.read(length)


@asyncio.coroutine
def read_and_emulate_mouse(fd):

    input_device = uinput.Device([
        uinput.BTN_LEFT,
        uinput.BTN_RIGHT,
        uinput.REL_WHEEL,
        uinput.ABS_X,
        uinput.ABS_Y,
        uinput.BTN_GEAR_DOWN,
        uinput.BTN_GEAR_UP,
    ])

    clicked = False
    rightClicked = False
    (lastX, lastY) = (0, 0)
    startTime = time.time()

    while True:
        try:
            touch_data = yield from async_read_data(fd, 14)
            if touch_data == 0:
                break;
        except IOError:
            return 0

        try:
            #(tag) = struct.unpack_from('>ccHH', touch_data)
            format = '<?BHH'
            #print('raw data:', touch_data)
            updateTouch(struct.unpack_from(format, touch_data, 1), input_device)
            updateTouch(struct.unpack_from(format, touch_data, 7), input_device)
        except Exception as e:
            traceback.print_exc()
            print('failed to update touch', e)
            #return 0

    fd.close()


if __name__ == "__main__":
    os.system("modprobe uinput")

    tasks = []
    loop = asyncio.get_event_loop()

    for i in range(0,5):
        touches.append(Touch(i))

    context = pyudev.Context()

    print("Checking devices already plugged-in...")
    for device in context.list_devices(subsystem='hidraw'):
        print('device', device)
    for device in context.list_devices(subsystem='hidraw'):
        check_device(device)

    print("Seeking monitor")
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='hidraw')
    print("Waiting for touch device connection...")

    for device in iter(monitor.poll, None):
        print("HID device notification.  ACTION: ", device.get('ACTION'))
#        print(device.device_node)

        if 'add' in (device.get('ACTION')):
            check_device(device)
