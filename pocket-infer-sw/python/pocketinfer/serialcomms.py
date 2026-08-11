import threading
import serial
import logging
from os.path import exists
from serial.tools import list_ports


class IOInterface:
    VID = 0x2886
    PID = 0x0058
    def __init__(self, port='/dev/ttyACM0', baud=115200, debug=False):
        self.logger = logging.getLogger(__name__)
        self.port = port
        self.baud = baud
        self.thread = threading.Thread()
        self.running = False
        self.waiting_for = False
        self.waiting_resp = None
        self.waiting_evt = threading.Event()
        self.cbs = []

    def subscribe(self, func):
        if func not in self.cbs:
            self.cbs.append(func)
    
    def unsubscribe(self, func):
        if func in self.cbs:
            self.cbs.remove(func)
    
    def open(self, port=None, baud=None):
        if port is not None:
            self.port = port
        if baud is not None:
            self.baud = baud
        try:
            self.ser = serial.Serial(self.port, self.baud)
        except serial.serialutil.SerialException:
            self.logger.info("Port not found, attempting autodetection")
            for port in list_ports.comports():
                if port.vid == self.VID and port.pid == self.PID:
                    self.port = port.device
                    break
            self.ser = serial.Serial(self.port, self.baud)
        self.running = True
        self.thread = threading.Thread(target=self.reader)
        self.thread.daemon = True
        self.thread.start()
    
    def reader(self):
        msg_buf = b''
        while self.running:
            if not self.ser.in_waiting:
                msg_buf += self.ser.read(1)
            if self.ser.in_waiting:
                msg_buf += self.ser.read(self.ser.in_waiting)
            while b'\r' in msg_buf or b'\n' in msg_buf:
                if b'\r' in msg_buf:
                    msg = msg_buf[:msg_buf.find(b'\r')].strip().rstrip()
                    if len(msg) > 0:
                        self.parse_msg(msg.decode('utf-8'))
                    msg_buf = msg_buf[msg_buf.find(b'\r')+1:]
                elif b'\n' in msg_buf:
                    msg = msg_buf[:msg_buf.find(b'\n')].strip().rstrip()
                    if len(msg) > 0:
                        self.parse_msg(msg.decode('utf-8'))
                    msg_buf = msg_buf[msg_buf.find(b'\n')+1:]
    
    def parse_msg(self, msg):
        if self.waiting_for and msg[0] == self.waiting_for:
            self.waiting_resp = msg
            self.waiting_evt.set()
            return
        for cb in self.cbs:
            try:
                cb(msg)
            except Exception:
                self.logger.exception("Exception encountered during cb, ignoring")
    
    def transact(self, msg, timeout=1.0):
        self.waiting_resp = None
        self.waiting_for = msg[0]
        self.waiting_evt.clear()
        if '\n' not in msg:
            msg += '\n'
        self.ser.write(msg.encode('utf-8'))
        self.waiting_evt.wait(timeout=timeout)
        self.waiting_for = None
        return self.waiting_resp
