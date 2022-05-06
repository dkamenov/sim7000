from machine import UART
from time import sleep
import re
import gc

class IllegalArgumentException(Exception):
    pass

class SimError(Exception):
    pass

class CmeError(Exception):
    pass

class CmsError(Exception):
    pass


class HttpResponse:
    
    def __init__(self, content=None, status_code=None, content_len=None, method=None):
        self.content=content
        self.content_len=content_len
        self.status_code=status_code
        self.method=method
    
    def text(self):
        return self.content.decode('utf-8')



class Sim7000:
    
    HTTPS_METHODS = {
        'GET': 1,
        'PUT': 2,
        'POST': 3,
        'PATCH': 4,
        'HEAD': 5
    }
    
    def __init__(self, device, baudrate, rx_pin=16, tx_pin=17):
        self.uart = UART(device, baudrate, rx=rx_pin, tx=tx_pin, bits=8, parity=None, stop=1, timeout=1000)
        sleep(2)
        self.uart.sendbreak()
        sleep(0.2)        
    
    def cmd(self, cmd):
        result = []
        cmd_prefix=re.match(r'^[A-Z]+', cmd).group(0)
        self.uart.write('AT+' + cmd + '\r')
        while True:
            buf = self.uart.readline()
            if not buf:
                continue
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
            if l.startswith(cmd) or not l:
                continue
            if l.startswith('OK'):
                return result
            if l.startswith('ERROR'):
                raise SimError(l)
            if l.startswith('+CME ERROR:'):
                raise CmeError(l.split(':')[1].strip())
            if l.startswith('+' + cmd_prefix):
                result.append(l)        
        
    def query(self, cmd):
        r = self.cmd(cmd)
        results = self._parse_result(r[0]) ## TODO: is this the correct response line? - check if command matches
        return results
        
    def _parse_result(self, l):
        str_vals = l.split(':')[1].split(',')
        return [eval(x.strip()) for x in str_vals]
    
    def wait_for(self, cmd):
        ''' Waits for response from cmd and returns parsed result '''
        while True:
            buf = self.uart.readline()
            if not buf:
                print('#', end='')
                continue
            
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
            if l.startswith('+' + cmd):
                return self._parse_result(l)
        
    def get_bearer_status(self, cid=1):
        r = self.query('SAPBR=2,{}'.format(cid))
        return r[1] if r[0] == cid else None

    def get_bearer_ip(self, cid=1):
        r = self.query('SAPBR=2,{}'.format(cid))
        return r[2] if r[0] == cid else None

    def open_bearer(self, cid=1):
        self.cmd('SAPBR=1,{}'.format(cid))
        
    def close_bearer(self, cid=1):
        self.cmd('SAPBR=0,{}'.format(cid)) 
        
    def set_bearer_param(self, cid=1, param_name="", param_value=""):
        if not param_name:
            raise IllegalArgumentException('param_name must be defined')
        self.cmd('SAPBR=3,{},"{}","{}"'.format(cid, param_name, param_value))     
    
    def ping(self):
        try:
            self.uart.write('AT\r')
            while True:
                buf = self.uart.readline()
                if not buf:
                    return False
                l = buf.decode('utf-8').rstrip()
                print('<---' + l)
                if l.startswith('OK'):
                    return True
                #if not l:
                #    return False
        except:
            return False
        
    def get_pin_status(self):
        try:
            r = self.cmd('CPIN?')
            if r[0].startswith('+CPIN:'):
                return r[0].split(':')[1].strip()
            return None
        except SimError:
            return None
        
    def init_network(self):
        print(self.cmd('CMEE=2')) # Use verbose error codes
        #print(self.cmd('COPS?'))  # Query Network information, operator and network mode
        #print(self.cmd('SAPBR=?'))
        #print(self.cmd('SAPBR=3,1,"APN","tfdata"')) # Specific for StraightTalk/ATT
        bs = self.get_bearer_status()
        if bs != 1:
            self.open_bearer()
            self.set_bearer_param(param_name="APN", param_value="tfdata")
        
        print("PIN Status: " + self.get_pin_status())
        
        print(self.cmd('CGDCONT=1,"IP",""')) # Configure APN for registration when needed
        print(self.cmd('CGNAPN')) # Query the APN delivered by the network after the CAT-M or NB-IOT network is successfully registered.
        
        r = self.cmd('CNACT?')
        status, ip_addr = self._parse_result(r[0])
        print("Network status: ", status)
        if int(status) == 0: 
            print(self.cmd('CNACT=1')) #Activate network
            sleep(5)
            r = self.cmd('CNACT?')    
    
    def reset(self):
        self.cmd('CFUN=6')
    
    def http_get(self, url):
        ''' Deprecated - use http() below ''' 
        try:
            print(self.cmd('HTTPTERM'))
        except:
            print('exception clearing HTTP state')
        
        self.cmd('HTTPINIT')
        self.cmd('HTTPPARA="CID",1')
        self.cmd('HTTPPARA="URL","{}"'.format(url))
        self.cmd('HTTPACTION=0')
        #self.cmd('HTTPSTATUS=?')
        method, status, response_len = self.wait_for('HTTPACTION')
        #self.cmd('HTTPSTATUS=?')
        self.cmd('HTTPREAD=0,{}'.format(response_len))
        self.cmd('HTTPTERM')
    
    
    def download_cert(self):
        f=open('cacerts/Amazon_Root_CA_1.crt', 'r')
        cert = f.read()
        size = len(cert)
        f.close()
        self.cmd('CFSINIT')
        self.uart.write('AT+CFSWFILE=3,"Amazon_Root_CA_1.crt",0,{},1000\r'.format(size)) # 3-file system, 1000 - timeout (ms)
        print("download command sent, waiting for confirm")
        while True:
            buf = self.uart.readline()
            if not buf:
                print('#', end='')
                continue
            
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
            if l.startswith('DOWNLOAD'):
                break

        print("Sending file...")
        bytes_written = self.uart.write(cert)
        print("Wrote {} bytes".format(bytes_written))
        self.uart.write('\r')
        self.cmd('CFSTERM')
        self.cmd('CSSLCFG="convert",2,"Amazon_Root_CA_1.crt"')
        
    
    def _get_host(self, url):
        return url.split('/')[2]

    def http(self, url, method='GET', body=None, headers={}):
        
        if self.query('SHSTATE?')[0] != 0: # Terminate previous connection if open
            self.cmd('SHDISC')
        
        if url.startswith('https:'):
            self.cmd('CSSLCFG="sslversion",1,3')
            #self.cmd('SHSSL=1,"Amazon_Root_CA_1.crt"')
            self.cmd('SHSSL=1,""') # !!! Need to set empty cert as #1 in order to skip cert validation!!

        host = self._get_host(url)
        # Mandatory params:
        schema = url.split(':')[0]
        self.cmd('SHCONF="URL","{}://{}"'.format(schema, host))
        self.cmd('SHCONF="BODYLEN",1024')
        self.cmd('SHCONF="HEADERLEN",350')
        
        if body:
            self.cmd('SHBOD="{}",{}'.format(body.replace('"', r'\"'), len(body)))

        self.cmd('SHCONN')
        for header_name, header_val in headers.items():
            self.cmd('SHAHEAD="{}","{}"'.format(header_name, header_val))

        method_code = Sim7000.HTTPS_METHODS[method.upper()]

        query_string = url.split(host)[1]
        if not query_string:
            query_string = '/'
            
        self.cmd('SHREQ="{}",{}'.format(query_string, method_code))
        method, status, response_len = self.wait_for('SHREQ')
        
        resp = HttpResponse(content_len=response_len, content=b'', method=method, status_code=status)
        if status <= 599:
            while len(resp.content) < response_len:
                self.cmd('SHREAD={},{}'.format(len(resp.content), response_len-len(resp.content)))            
                while True:
                    gc.collect()
                    buf = self.uart.readline()
                    if not buf:
                        break
                    line = buf.decode('utf-8').rstrip()
                    if not line.startswith('+SHREAD:'):
                        print('<---{}'.format(line))
                        continue
                    bytes_to_read = self._parse_result(line)[0]
                    print("---------------reading {}b -----------".format(bytes_to_read))
                    buf = self.uart.read(bytes_to_read)
                    resp.content += buf
                    print("--------------- {} of {}b read so far -----------".format(len(buf), len(resp.content)))
                    if len(buf) < bytes_to_read:
                        break

                    if len(resp.content) >= response_len:
                        print("--------------- A total of {}b were read ------------".format(len(resp.content)))
                        break
                                
        self.cmd('SHDISC')
        gc.collect()
        return resp

