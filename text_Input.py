import os
import mmap
import struct
import socket
import multiprocessing as mp
from time import sleep

#My code for POSIX... Windows Ommitted.
class keyboard_input():
    def __enter__(self):
        self.opsys = os.name
        if self.opsys == "posix":
            import sys, termios, signal
            self.fd = sys.stdin.fileno()
            self.old_term = termios.tcgetattr(self.fd)
            new_term = termios.tcgetattr(self.fd)
            new_term[3] = (new_term[3] & ~termios.ICANON & ~termios.ECHO)
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, new_term)
            signal.signal(signal.SIGINT, self.interrupt_handler)
            signal.signal(signal.SIGCONT, self.interrupt_handler)
        else:
            print("Incompatible OS Error.")
        print("\033[?25l", end = "")
        return self

    def __exit__(self, type, value, traceback):
        print("\033[?25h", end = "", flush = True)
        if self.opsys == "posix":
            import termios
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)
            new_term = termios.tcgetattr(self.fd)
            new_term[3] = (new_term[3] | termios.ICANON | termios.ECHO)
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, new_term)

    def __call__(self, keys=["en"]):
        if self.opsys == "posix":
            import sys, select
            local = select.poll()
            local.register(sys.stdin, select.POLLIN)
            if not local.poll(1) == []:
                in_var = [n for n in sys.stdin.buffer.read1(10)]
                if ('en' in keys) and in_var[0] == ord('\n'):
                    return 'en'
                if chr(in_var[0]) in keys:
                    return chr(in_var[0])
                if chr(in_var[0]).isnumeric():
                    return chr(in_var[0])

    def interrupt_handler(self, signum, stack_frame):
        import signal
        import sys
        if signum == signal.SIGINT:
            self.__exit__(None, None, None)
            sys.exit()
            return
        if signum == signal.SIGCONT:
            self.__enter__()
            return

##This mimics the input without enter. 
# But it's a pain in the rear to manage this stuff
# if __name__ == "__main__":
    # with keyboard_input() as ki:
    #     while True:
    #         c = ki(valid_input)
    #         if c != None:
    #             print(c)+

### CONSTANTS
valid_input = ["en", "U", "u", "D", "d", "F", "T"]
REGISTER_MEMORY_OFFSET  = 0x43c00000
FIFO_MEMORY_OFFSET      = 0x43c10000
CODEC_MEMORY_OFFSET     = 0x41600000

#Ref Course Documents
class register:
    FREQ = 0
    TUNE = 1
    RST  = 2
    TIME = 3
    def __init__(self):
        self.f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.m = mmap.mmap(self.f, 4096, offset = REGISTER_MEMORY_OFFSET)
    
    def __del__(self):
        os.close(self.f)

    def read(self, reg):
        if reg >=0 and reg < 4:
            local_offset = reg * 4
            regval = struct.unpack("<L", self.m[local_offset:local_offset+4])[0]
        if reg == register.FREQ or reg == register.TUNE:
            val = regval*(125.0e6)/(1<<27)
        else:
            val = regval
        print(f"register read: {val}")
        return int(round(val))

    def write(self, reg, val):
        if reg == register.FREQ or reg == register.TUNE:
            regval = val*(1<<27)/(125.0e6)
        else:
            regval = val
        if reg >=0 and reg < 4:
            local_offset = reg * 4
            self.m[local_offset:local_offset+4] = struct.pack("<L", int(round(regval)))

#Ref Xilinx PG080
class fifo:
    REC_RST     = 0x18
    REC_DATA    = 0x20
    REC_CNT     = 0x24
    AXI_RST     = 0x28
    def __init__(self):
        self.f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.m = mmap.mmap(self.f, 4096, offset = FIFO_MEMORY_OFFSET)
        self.reset()
    
    def __del__(self):
        os.close(self.f)

    def reset(self):
        self.m[fifo.REC_RST:fifo.REC_RST+4] = struct.pack("<L", 0xA5)
        self.m[fifo.AXI_RST:fifo.AXI_RST+4] = struct.pack("<L", 0xA5)
    
    def read(self, val):
        received_data = []
        for i in range(0, val):
            received_data.append(struct.unpack("<L", self.m[fifo.REC_DATA:fifo.REC_DATA+4])[0])
        return received_data
    
    def count(self):
        available = (0xFFFFFFF & int(struct.unpack("<L", self.m[fifo.REC_CNT:fifo.REC_CNT+4])[0]))//4
        return available//4

#Ref Xilinx DS756
## NOT FUNCTIONAL
class codec:
    SOFT_RST    = 0x040
    IIC_DATA    = 0x108
    IIC_ADDR    = 0x110
    def __init__(self):
        self.f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.m = mmap.mmap(self.f, 4096, offset = CODEC_MEMORY_OFFSET)
        self.reset()
    
    def __del__(self):
        os.close(self.f)

    def reset(self):
        self.m[fifo.SOFT_RST:fifo.SOFT_RST+4] = struct.pack("<L", 0xA)
    
    def write(self, reg, val):
        self.m[codec.IIC_ADDR:codec.IIC_ADDR+4] = struct.pack("<L", int(reg))
        self.m[codec.IIC_DATA:codec.IIC_DATA+4] = struct.pack("<L", int(val))

#Ref https://wiki.python.org/moin/UdpCommunication
class packet:
    DEFAULT_IP = "192.168.4.5"
    DEFAULT_PORT = 25344
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_ip = self.DEFAULT_IP
        self.target_port = self.DEFAULT_PORT
        self.frame_counter = 0
    
    def update(self, ip = "", port = ""):
        if ip != "":
            self.target_ip=ip
        if port != "":
            self.target_port=port

    def send(self, message):
        if type(message)==type(b'place'):
            header = struct.pack("<H", self.frame_counter)
            self.sock.sendto(header + message, (self.target_ip, self.target_port))
            self.frame_counter =  self.frame_counter + 1
            if self.frame_counter > 65535:
                self.frame_counter = 0
        else:
            print(type(message))
            print("gimme byte >:((")

#Ref https://docs.python.org/3/library/multiprocessing.html
class streamer:
    def __init__(self, streamer_fifo, streamer_packet):
        self.fifo = streamer_fifo
        self.packet = streamer_packet
        self.proc = mp.Process(target = self.send_loop)
        self.proc.daemon = True
    
    def __del__(self):
        self.stop_loop()

    def update(self, streamer_fifo, streamer_packet):
        self.fifo = streamer_fifo
        self.packet = streamer_packet

    def start_loop(self):
        self.stop_loop()
        self.proc = mp.Process(target = self.send_loop)
        self.proc.start()
        
    def stop_loop(self):
        if self.proc.is_alive():
            self.proc.kill()

    def send_loop(self):
        while(True):
            if self.fifo.count() > 256:
                data = self.fifo.read(256)
                packed_data = struct.pack("<256L", *data)
                self.packet.send(packed_data)
            else:
                # print(self.fifo.count())
                pass


if __name__ == "__main__":
    # Here be ye major objects
    reg     = register()
    pack    = packet()
    fi      = fifo()
    stream  = streamer(streamer_fifo = fi, streamer_packet = pack)

    disp_freq = reg.read(register.FREQ)
    disp_tune = reg.read(register.TUNE)
    print("\033[H\033[0J", end = "")
    while True:
        print("\033[H", end = "")
        print(f"Welcome to the SDR, this time with filters, mixer, and much more... I lost track...")
        print(f"My creator is Jackson Long.")
        print(f"NOTE: Interface written with VT100 in mind, please use a compatible terminal.")
        print(f"NOTE: Frequeny Calculations use fp-int truncation and may not work perfectly.")
        print(f"These are your options, press \"enter\" after each command:")
        print(f" U  nn : Increase Frequency by nn * 1000Hz.")
        print(f" u  nn : Increase Frequency by nn *  100Hz.")
        print(f" d  nn : Decrease Frequency by nn *  100Hz.")
        print(f" D  nn : Decrease Frequency by nn * 1000Hz.")
        print(f" F  nn : Set Fake-ADC Frequency to nn.  Current Freq: \033[K{disp_freq:>8} Hz")
        print(f" T  nn : Set Tune Frequency to nn. Current Tune Freq: \033[K{disp_tune:>8} Hz")
        print(f" IP ss : Set the IP Address to ss.    Current IP:\033[K{pack.target_ip}")
        print(f" START : Begins Streaming to IP Address, Default:\033[K{packet.DEFAULT_IP}.")
        print(f" STOP  : Stops Streaming to IP Address.")
        command = input("Your Command: \033[0J")
        command_array = [comm for comm in command.split(" ") if len(comm) > 0 ]
        if len(command_array) > 0:
            if command_array[0] in "UuDd":
                local_freq = reg.read(register.FREQ)
                multiplier = 1
                if len(command_array) > 1:
                    try:
                        multiplier = int(command_array[1])
                    except ValueError:
                        print("Received Bad Input.")
                if command_array[0] == "U":
                    local_freq = local_freq + 1000*multiplier
                if command_array[0] == "u":
                    local_freq = local_freq + 100*multiplier
                if command_array[0] == "d":
                    local_freq = local_freq - 100*multiplier
                if command_array[0] == "D":
                    local_freq = local_freq - 1000*multiplier
                if local_freq < 0:
                    local_freq = 0
                if local_freq > 125000000:
                    local_freq = 125000000
                reg.write(register.FREQ, local_freq)
                disp_freq = local_freq

            if command_array[0].upper() == "F":
                try:
                    local_freq = int(command_array[1])
                    reg.write(register.FREQ, local_freq)
                    disp_freq = local_freq
                    print("Changing fake ADC Frequency", end ="")
                except ValueError:
                    print("Received Bad Input.")
                    sleep(1)

            if command_array[0].upper() == "T":
                try:
                    local_tune = int(command_array[1])
                    reg.write(register.TUNE, local_freq)
                    disp_tune = local_tune
                    print("Changing Tune", end ="")
                except ValueError:
                    print("Received Bad Input.")
                    sleep(1)

            if command_array[0].upper() == "IP":
                print("Changing IP", end ="")
                target_ip = command_array[1]
                stream.stop_loop()
                pack.update(ip=target_ip)
                stream.update(streamer_fifo = fi, streamer_packet = pack)
                stream.start_loop()

            if command_array[0].upper() == "START":
                print("Starting", end ="")
                stream.start_loop()
            
            if command_array[0].upper() == "STOP":
                print("Stopping", end ="")
                stream.stop_loop()

            for i in range(3):
                print(". ", end ="", flush =True)
                sleep(.5)
        
