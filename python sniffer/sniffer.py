import serial
import time
import datetime

VERSION = "1.2"

# Configuration constants
MNET_COM_PORT = '/dev/ttyS0'  # Adjust as per your setup
BAUD_RATE = 9600
TIMEOUT = 10  # Timeout in seconds
MAX_DATA = 20
COOLMASTER_ADDR = 0xfb
ACK = 0x06
NAK = 0x21

# Global variables
packet = bytearray(MAX_DATA + 6)
raw_datacount = 0
crc = 0
prev_from_addr = 0
prev_to_addr = 0
filter_unit = -1  # Unit to filter for; -1 is none
mnet_active = False
skipping_packet = False
filtering_packet = False
logfile = None

def delta_time(start_time):
    delta = datetime.datetime.now() - start_time
    return int(delta.total_seconds() * 1000)

def open_serial(port, baudrate):
    return serial.Serial(port, baudrate, timeout=TIMEOUT)

def close_serial(ser):
    ser.close()

def output(fmt, *args):
    message = fmt % args
    print(message, end="")
    logfile.write(message)

def newline():
    global raw_datacount, crc, skipping_packet
    output("\n")
    raw_datacount = 0
    crc = 0

def showtime(delta):
    output("%5d.%03d  " % (delta // 1000, delta % 1000))

def print_addr(addr):
    if addr == COOLMASTER_ADDR:
        output("CM")
    else:
        output("%02X" % addr)

def showtemp(pos):
    deg_c = packet[pos] * 10 + (packet[pos + 1] >> 4) + (packet[pos + 1] & 0xf) / 10.0
    output(" %.1f deg C, %.1f deg F" % (deg_c, deg_c * 9 / 5 + 32))

def showfanspeed(pos):
    parm = packet[pos]
    output(" %s" % ("low" if parm == 4 else "medium" if parm == 5 else "high" if parm == 6 else "auto" if parm == 0x0b else "???"))

def poweron():
    parm = packet[2]
    output("turn %s" % ("on" if parm == 1 else "off" if parm == 0 else "??"))

def poweron_ack():
    output(" ok")

def getstatus():
    output("get status")

def getstatus_ack():
    parm = packet[2]
    output("%s" % (" stopped" if parm == 0 else " running" if parm == 1 else "???"))

def getmode():
    output("get mode")

def getmode_ack():
    parm = packet[2]
    output("%s" % (" heat" if parm == 7 else " cool" if parm == 8 else " fan only" if parm == 0x0d else "???"))

def getsetpoint():
    output("get setpoint temp")

def getsetpoint_ack():
    showtemp(2)

def getfanspeed():
    output("get fan speed")

def getfanspeed_ack():
    showfanspeed(2)

def setfanspeed():
    output("set fan speed")
    showfanspeed(2)

def setfanspeed_ack():
    output(" ok")

def getcurrenttemp():
    output("get current temp")

def getcurrenttemp_ack():
    showtemp(3)

def setmode():
    parm = packet[2]
    output("set mode %s" % ("heat" if parm == 7 else "cool" if parm == 8 else "auto" if parm == 32 else "???"))

def setmode_ack():
    output(" ok")

def settemp():
    output("set temp ")
    showtemp(2)

def settemp_ack():
    output(" ok")

pkt_formats = [
    ([0xff, 0xff, 0xff], [5, 0x0d, 0x01], poweron),
    ([0xff, 0xff, 0xff, 0xff], [3, 0x0d, 0x81, 0x00], poweron_ack),
    ([0xff, 0xff, 0xff], [3, 0x0d, 0x02], setmode),
    ([0xff, 0xff, 0xff, 0xff], [3, 0x0d, 0x82, 0x00], setmode_ack),
    ([0xff, 0xff, 0xff], [5, 0x05, 0x01], settemp),
    ([0xff, 0xff, 0xff, 0xff], [3, 0x05, 0x81, 0x00], settemp_ack),
    ([0xff, 0xff, 0xff], [3, 0x0d, 0x0e], setfanspeed),
    ([0xff, 0xff, 0xff, 0xff], [3, 0x0d, 0x8e, 0x00], setfanspeed_ack),
    ([0xff, 0xff, 0xff], [2, 0x2d, 0x01], getstatus),
    ([0xff, 0xff, 0xff], [5, 0x2d, 0x81], getstatus_ack),
    ([0xff, 0xff, 0xff], [2, 0x2d, 0x02], getmode),
    ([0xff, 0xff, 0xff], [3, 0x2d, 0x82], getmode_ack),
    ([0xff, 0xff, 0xff], [2, 0x25, 0x01], getsetpoint),
    ([0xff, 0xff, 0xff], [5, 0x25, 0x81], getsetpoint_ack),
    ([0xff, 0xff, 0xff], [2, 0x2d, 0x0e], getfanspeed),
    ([0xff, 0xff, 0xff], [3, 0x2d, 0x8e], getfanspeed_ack),
    ([0xff, 0xff, 0xff, 0xff], [3, 0x35, 0x03, 0x22], getcurrenttemp),
    ([0xff, 0xff, 0xff, 0xff], [5, 0x35, 0x83, 0x22], getcurrenttemp_ack),
]

def decode_packet():
    global raw_datacount, crc, skipping_packet, prev_from_addr, prev_to_addr
    delta = 0
    if raw_datacount >= 5:
        packet_len = packet[4]
        if raw_datacount == 6 + packet_len:
            if crc != 0:
                output("*** bad CRC *** ")
                for i in range(raw_datacount):
                    output("%02X ", packet[i])
                output("\n")
                skipping_packet = True
                crc = 0
        if raw_datacount == 7 + packet_len:
            if not filtering_packet:
                showtime(delta)
                for i in range(raw_datacount):
                    output("%02X ", packet[i])
                match_packet()
                newline()
            filtering_packet = False
            crc = 0
            raw_datacount = 0

def match_packet():
    global prev_from_addr, prev_to_addr
    packet_len = packet[4]
    for fmt in pkt_formats:
        match = True
        for i in range(len(fmt[0])):
            if (packet[4 + i] & fmt[0][i]) != fmt[1][i]:
                match = False
                break
        if match:
            fmt[2]()
            break
    else:
        output("???")

def main():
    global raw_datacount, crc, skipping_packet, mnet_active, filtering_packet, logfile
    start_time = datetime.datetime.now()

    with open("log.txt", "a") as logfile:
        ser = open_serial(MNET_COM_PORT, BAUD_RATE)
        mnet_active = True
        try:
            while mnet_active:
                c = ser.read(1)
                if len(c) == 1:
                    crc += c[0]
                    if raw_datacount < MAX_DATA:
                        packet[raw_datacount] = c[0]
                        raw_datacount += 1
                    else:
                        if not skipping_packet:
                            output("***too much data ")
                            skipping_packet = True
                    if raw_datacount == 4 and not skipping_packet:
                        if filter_unit == -1 or packet[1] == filter_unit or packet[2] == filter_unit:
                            delta = delta_time(start_time)
                        else:
                            filtering_packet = True
                    decode_packet()
                else:
                    if not skipping_packet:
                        newline()
                        delta = delta_time(start_time)
                        showtime(delta)
                        newline()
                        skipping_packet = False
        except KeyboardInterrupt:
            pass
        finally:
            close_serial(ser)

if __name__ == "__main__":
    main()