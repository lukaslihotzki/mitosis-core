#!/usr/bin/env python

from ast import expr_context
import toml
import paramiko
import getpass
import argparse
import time
import select
import subprocess

import os

from paramiko import SSHConfig

use_ssh_config = False

config = SSHConfig()
try:
    with open(os.path.expanduser("~/.ssh/config")) as _file:
        config.parse(_file)
except:
    pass

class RunPrinter:
    def __init__(self,name,c,o):
        self.c = c
        self.name = name
        self.order = o

    def print_one(self):
        if self.c.recv_ready():
            res = self.c.recv(8192).decode().splitlines()
            for l in res:
                print("@%-10s" % self.name,l.strip())

        if self.c.recv_stderr_ready():
            res = self.c.recv_stderr(8192).decode().splitlines()
            for l in res:
                print("@%-10s" % self.name,l.strip())

        if self.c.exit_status_ready():
#            print("exit status ready: ",self.c.recv_exit_status(), self.c.recv_ready())
            while self.c.recv_ready():
                res = self.c.recv(8192).decode().splitlines()
                for l in res:
                    print("@%-10s" % self.name,l.strip())                
            while self.c.recv_stderr_ready():
                res = self.c.recv_stderr(8192).decode().splitlines()
                for l in res:
                    print("@%-10s" % self.name,l.strip())                
            print("exit ",self.name)
            return False

        return True

def check_keywords(lines,keywords,black_keywords):
    match = []
    for l in lines:
        black = False
        for bk in black_keywords:
            if l.find(bk) >= 0:
                black = True
                break
        if black:
            continue
        flag = True
        for k in keywords:
            flag = flag and (l.find(k) >= 0)
        if flag:
            #print("matched line: ",l)
            match.append(l)
    return len(match)

class Envs:
    def __init__(self,f = ""):
        self.envs = {}
        self.history = []
        try:
            self.load(f)
        except:
            pass

    def set(self,envs):
        self.envs = envs
        self.history += envs.keys()

    def load(self,f):
        self.envs = pickle.load(open(f, "rb"))

    def add(self,name,env):
        self.history.append(name)
        self.envs[name] = env

    def append(self,name,env):
        self.envs[name] = (self.envs[name] + ":" + env)

    def delete(self,name):
        self.history.remove(name)
        del self.envs[name]

    def __str__(self):
        s = ""
        for name in self.history:
            s += ("export %s=%s;" % (name,self.envs[name]))
        return s

    def store(self,f):
        with open(f, 'wb') as handle:
            pickle.dump(self.envs, handle, protocol=pickle.HIGHEST_PROTOCOL)

class ConnectProxy:
    def __init__(self,mac,user="",passp=""):
        if user == "": ## use the server user as default
            user = getpass.getuser()
        self.ssh = paramiko.SSHClient()

        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.user = user
        self.mac  = mac
        self.sftp = None
        self.passp = passp

    def connect(self,pwd,passp=None,timeout = 30):
        user_config = config.lookup(self.mac)
        if user_config and use_ssh_config:
            print("connect", self.mac, user_config)
            #print(user_config)
            #cfg = {'hostname': self.mac, 'username': self.user}
            #cfg['sock'] = paramiko.ProxyCommand(user_config['proxycommand'])
            return self.ssh.connect(hostname = self.mac,username = self.user, password = pwd,
                                    timeout = timeout, allow_agent=False,look_for_keys=False,passphrase=passp,sock=paramiko.ProxyCommand(user_config['proxycommand']),banner_timeout=400)

        else:
            return self.ssh.connect(hostname = self.mac,username = self.user, password = pwd,
                                    timeout = timeout, allow_agent=False,look_for_keys=False,passphrase=passp)

    def connect_with_pkey(self,keyfile_name,timeout = 10):
        print("connect with pkey")
        user_config = config.lookup(self.mac)
        print(user_config)
        if user_config:
            assert False

        self.ssh.connect(hostname = self.mac,username = self.user,key_filename=keyfile_name,timeout = timeout)

    def execute(self,cmd,pty=False,timeout=None,background=False):
        if not background:
            return self.ssh.exec_command(cmd,get_pty=pty,timeout=timeout)
        else:
            print("exe",cmd,"in background")
            transport = self.ssh.get_transport()
            channel = transport.open_session()
            return channel.exec_command(cmd)

    def execute_w_channel(self,cmd):
        print("emit", cmd,"@",self.mac)
        transport = self.ssh.get_transport()
        channel = transport.open_session()
        channel.get_pty()
        channel.exec_command(cmd)
        return channel


    def copy_file(self,f,dst_dir = ""):
        if self.sftp == None:
            self.sftp = paramiko.SFTPClient.from_transport(self.ssh.get_transport())
        self.sftp.put(f, dst_dir + "/" + f)

    def get_file(self,remote_path,f):
        if self.sftp == None:
            self.sftp = paramiko.SFTPClient.from_transport(self.ssh.get_transport())
        self.sftp.get(remote_path + "/" + f,f)

    def close(self):
        if self.sftp != None:
            self.sftp.close()
        self.ssh.close()

    def copy_dir(self, source, target,verbose = False):

        if self.sftp == None:
            self.sftp = paramiko.SFTPClient.from_transport(self.ssh.get_transport())

        if os.path.isfile(source):
            return self.copy_file(source,target)

        try:
            os.listdir(source)
        except:
            print("[%S] failed to put %s" % (self.mac,source))
            return

        self.mkdir(target,ignore_existing = True)

        for item in os.listdir(source):
            if os.path.isfile(os.path.join(source, item)):
                try:
                    self.sftp.put(os.path.join(source, item), '%s/%s' % (target, item))
                    print_v(verbose,"[%s] put %s done" % (self.mac,os.path.join(source, item)))
                except:
                    print("[%s] put %s error" % (self.mac,os.path.join(source, item)))
            else:
                self.mkdir('%s/%s' % (target, item), ignore_existing=True)
                self.copy_dir(os.path.join(source, item), '%s/%s' % (target, item))

    def mkdir(self, path, mode=511, ignore_existing=False):
        try:
            self.sftp.mkdir(path, mode)
        except IOError:
            if ignore_existing:
                pass
            else:
                raise

class Courier2:
    def __init__(self,user=getpass.getuser(),pwd="123",hosts = "hosts.xml",passp="",curdir = ".",keyfile = ""):
        self.user = user
        self.pwd = pwd
        self.keyfile = keyfile
        self.cached_host = "localhost"
        self.passp = passp

        self.curdir = curdir
        self.envs   = Envs()

    def cd(self,dir):
        if os.path.isabs(dir):
            self.curdir = dir
            if self.curdir == "~":
                self.curdir = "."
        else:
            self.curdir += ("/" + dir)

    def get_file(self,host,dst_dir,f,timeout=None):
        p = ConnectProxy(host,self.user)
        try:
            if len(self.keyfile):
                p.connect_with_pkey(self.keyfile,timeout)
            else:
                p.connect(self.pwd,timeout = timeout)
        except Exception as e:
            print("[get_file] connect to %s error: " % host,e)
            p.close()
            return False,None
        try:
            p.get_file(dst_dir,f)
        except Exception as e:
            print("[get_file] get %s @%s error " % (f,host),e)
            p.close()
            return False,None
        if p:
            p.close()

        return True,None

    def copy_file(self,host,f,dst_dir = "~/",timeout = None):
        p = ConnectProxy(host,self.user)
        try:
            if len(self.keyfile):
                p.connect_with_pkey(self.keyfile,timeout)
            else:
                p.connect(self.pwd,timeout = timeout)
        except Exception as e:
            print("[copy_file] connect to %s error: " % host,e)
            p.close()
            return False,None
        try:
            p.copy_file(f,dst_dir)
        except Exception as e:
            print("[copy_file] copy %s error " % host,e)
            p.close()
            return False,None
        if p:
            p.close()

        return True,None

    def execute_w_channel(self,cmd,host,dir,timeout = None):
        p = ConnectProxy(host,self.user)
        try:
            if len(self.keyfile):
                p.connect_with_pkey(self.keyfile,timeout)
            else:
                p.connect(self.pwd,self.passp,timeout = timeout)
        except Exception as e:
            print("[pre execute] connect to %s error: " % host,e)
            p.close()
            return None,e

        try:
            ccmd = ("cd %s" % dir) + ";" + str(self.envs) + cmd
            return p.execute_w_channel(ccmd)
        except:
            return None


    def pre_execute(self,cmd,host,pty=True,dir="",timeout = None,retry_count = 3,background=False):
        if dir == "":
            dir = self.curdir

        p = ConnectProxy(host,self.user)
        try:
            if len(self.keyfile):
                p.connect_with_pkey(self.keyfile,timeout)
            else:
                p.connect(self.pwd,timeout = timeout)
        except Exception as e:
            print("[pre execute] connect to %s error: " % host,e)
            p.close()
            return None,e

        try:
            ccmd = ("cd %s" % dir) + ";" + str(self.envs) + cmd
            if not background:
                _,stdout,_ = p.execute(ccmd,pty,timeout,background = background)
                return p,stdout
            else:
                c = p.execute(ccmd,pty,timeout,background = True)
                return p,c
        except Exception as e:
            print("[pre execute] execute cmd @ %s error: " % host,e)
            p.close()
            if retry_count > 0:
                if timeout:
                    timeout += 2
                return self.pre_execute(cmd,host,pty,dir,timeout,retry_count - 1)

    def execute(self,cmd,host,pty=True,dir="",timeout = None,output = True,background=False):
        ret = [True,""]
        p,stdout = self.pre_execute(cmd,host,pty,dir,timeout,background = background)
        if p and (stdout and output) and (not background):
            try:
                while not stdout.channel.closed:
                    try:
                        for line in iter(lambda: stdout.readline(2048), ""):
                            if pty and (len(line) > 0): ## ignore null lines
                                print((("[%s]: " % host) + line))
                            else:
                                ret[1] += (line + "\n")
                    except UnicodeDecodeError as e:
                        continue
                    except Exception as e:
                        break
            except Exception as e:
                print("[%s] execute with execption:" % host,e)
        if p and (not background):
            p.close()
        #            ret[1] = stdout
        else:
            ret[0] = False
            ret[1] = stdout
        return ret[0],ret[1]

#cr.envs.set(base_env)
def str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
#    raise ValueError(f'{value} is not a valid boolean value')

def get_order(p):
    try:
        return int(p["order"])
    except:
        return 0    

def main():
    global use_ssh_config
    arg_parser = argparse.ArgumentParser(
        description=''' Benchmark script for running the cluster''')
    arg_parser.add_argument(
        '-f', metavar='CONFIG', dest='config', default="run.toml",nargs='+',
        help='The configuration files to execute commands')

    arg_parser.add_argument('-b','--black', nargs='+', help='hosts to ignore', required=False)
    arg_parser.add_argument('-n','--num', help='num-passes to run', default = 128,type=int)
    arg_parser.add_argument('-k','--proxy_command', help='whether to use proxy_command in ssh_config', default = False,type=str_to_bool)
    arg_parser.add_argument('-u','--user', help='user name', default = "",type=str)
    arg_parser.add_argument('-p','--pwd', help='password', default = "",type=str)
    args = arg_parser.parse_args()

    num = args.num
    use_ssh_config = args.proxy_command
    print('use proxy command', args.proxy_command)

    black_list = {}
    if args.black:
        for e in args.black:
            black_list[e] = True

    printer = []
    runned = 0

    for c in args.config:
        config = toml.load(c)
        user = config.get("user","")

        pwd  = config.get("pwd","")
        passp = config.get("passphrase",None)
        global_configs = config.get("global_configs","")

        cr = Courier2(user,pwd,passp=passp)

        ## now execute
        passes = config.get("pass",[])
        execution_queue = []        

        global_execution_order = 0

        for p in passes:
            execution_queue.append(p) 
        execution_queue.sort(key=lambda x : get_order(x))

        ## restrict the number of running process
        execution_queue = execution_queue[0:num]

        idx = -1
        for p in execution_queue:
            if get_order(p) <= global_execution_order: 
                idx += 1
            else:
                break
        must_run_queue = execution_queue[0:idx + 1]
        execution_queue = execution_queue[idx + 1:]

        ## emit all the must run queues 
        for (i,p) in enumerate(must_run_queue):
            if runned > num:
                break

            if p["host"] in black_list:
                continue

            runned += 1

            if p.get("local","no") == "yes":
                subprocess.run(p["cmd"].split(" "))
                pass
            else:
                res = cr.execute_w_channel(p["cmd"] + " " + global_configs,
                                           p["host"],
                                           p["path"])
                if p["host"] not in config.get("null",[]):
                    printer.append(RunPrinter(str(i) + p["host"],res, get_order(p)))                    

#            if "pend" in dict(p).keys():
#                pend = float(p["pend"])
#                time.sleep(pend)

    while len(printer) > 0 or len(execution_queue) > 0:
        temp = []
        for p in printer:
            if p.print_one():
                temp.append(p)
            else:
                if global_execution_order <= p.order:
                    global_execution_order += 1

        printer = temp

        ## check whether we are ok        
        while True:
            if len(execution_queue) > 0 and get_order(execution_queue[0]) <= global_execution_order:
                p = execution_queue.pop(0)

                ## issue another
                res = cr.execute_w_channel(p["cmd"] + " " + global_configs,
                                           p["host"],
                                           p["path"])
                if p["host"] not in config.get("null",[]):
                    printer.append(RunPrinter(str(i) + p["host"],res, get_order(p)))                
            else:
                break

if __name__ == "__main__":
    main()
