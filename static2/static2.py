#!/usr/bin/env python2.7
# coding: utf-8

# NO MORE RADARE
# tags should be dynamically generated
#   like when you request the 'instruction' tag, it triggers the disassembly
#   when you set the 'name' tag, it dedups names, and updates the reverse index
#   when you set the 'scope' tag, it adds it as a member of the function
# so it's a "managed" key value store
# don't worry at all about caching unless things are too slow

# stuff from Program should be moved here
#   this class should contain all of the information about an independent run of the binary
# move the webserver code out of here, and perhaps into qira_webserver


# *** EXISTING TAGS ***
# len -- bytes that go with this one
# name -- name of this address
# comment -- comment on this address
# instruction -- string of this instruction
# arch -- arch of this instruction
# crefs -- code xrefs
# type -- type of instruction


# objects are allowed in the key-value store,
#   but they should do something sane for the javascript on repr

# fhex and ghex shouldn't be used
# all addresses are numbers

import collections
import os, sys
import re
import pickle
import atexit
from hashlib import sha1

sys.path.append("../middleware")
import qira_config

from model import *

# the new interface for all things static
# will only support radare2 for now
# mostly tags, except for names and functions
class Static:
  def __init__(self, path, debug=0, static_engine=None):
    # create the static cache dir
    try:
      os.mkdir(qira_config.STATIC_CACHE_BASE)
    except:
      pass

    self.tags = {}
    self.path = path
    self.scf = qira_config.STATIC_CACHE_BASE + sha1(open(self.path, "rb").read()).hexdigest()
    self.r2core = None
    self.debug = debug

    # add -yuike
    self.traces = {}
    self.lib_f = []

    # radare doesn't seem to have a concept of names
    # doesn't matter if this is in the python
    self.rnames = {}

    # fall through on an instruction
    # 'arch'
    self.global_tags = Tags(self)
    self.global_tags['functions'] = set()
    self.global_tags['blocks'] = set()
    self.global_tags['segments'] = []

    # concept from qira_program
    self.base_memory = {}

    # pass static engine as an argument for testing
    # default is "builtin" -yuike
    if static_engine is None:
      static_engine = qira_config.STATIC_ENGINE

    # TODO: clean this up
    if static_engine == "r2":
      sys.path.append(os.path.join(qira_config.BASEDIR, "static2", "r2"))
      import r2pipe 
      import loader 
      import analyzer
      self.r2core = r2pipe.r2pipe(path)
      # capstone is not working ok yet, so using udis for now
      self.r2core.cmd("e asm.arch=x86.udis")
      self.r2core.cmd("aa;af @ main")
    elif static_engine == "ida":
      # run the elf loader
      sys.path.append(os.path.join(qira_config.BASEDIR, "static2", "ida"))
      import ida
      class loader():
        @staticmethod
        def load_binary(static):
          ida.init_with_binary(static.path)
      class analyzer():
        @staticmethod
        def analyze_functions(x):
          dat = ida.fetch_tags()
          print dat
    else:
      # run the elf loader
      # qira/static2/builtin 以下のファイルをインポート可能に -yuike
      sys.path.append(os.path.join(qira_config.BASEDIR, "static2", "builtin"))
      import loader
      import analyzer
    self.analyzer = analyzer
    loader.load_binary(self) # ELFバイナリを解析

    if self.debug >= 1:
      print "*** elf loaded"

    """
    # check the cache
    if os.path.isfile(self.scf):
      # cache is global_tags + tags
      with open(self.scf) as f:
        try:
          dd = pickle.load(f)
          print "*** read %d bytes from static cache" % f.tell()
        except:
          dd = None
          print "*** static cache corrupt, ignoring"
        if dd != None:
          self.deserialize(dd)
      pass

    # register cache writing
    def write_cache():
      with open(self.scf, "wb") as f:
        dat = self.serialize()
        pickle.dump(dat, f)
        print "*** wrote %d bytes to static cache" % f.tell()

    atexit.register(write_cache)
    """

  def serialize(self):
    def blacklist(d):
      ret = {}
      for k in d:
        #if k == "instruction":
        if k != "name":
          continue
        ret[k] = d[k]
      return ret
    kk = self.tags.keys()
    vv = map(lambda x: blacklist(self.tags[x].backing), kk)
    return self.global_tags.backing, kk, vv

  def deserialize(self, dat):
    gt, kk, vv = dat
    for k in gt:
      self[k] = gt[k]

    for address, dd in zip(kk, vv):
      for k in dd:
        self[address][k] = dd[k]

  # this should be replaced with a 
  def set_name(self, address, name):
    if name not in self.rnames:
      self.rnames[name] = address
    elif address != self.rnames[name]:
      # add underscore if name already exists
      return self.set_name(address, name+"_")
    return name

  def _auto_update_name(self, address, name):
    '''modifies the name of address based on data from analyses
       but if we already have a name (from a user or symbols) do nothing'''
    if not self[address]['name']:
      self[address]['name'] = name

  def get_address_by_name(self, name):
    if name in self.rnames:
      return self.rnames[name]
    else:
      return None

  def _insert_names(self,st):
    '''TODO kind of fugly
       takes in a string and replaces things like 0x???????? with
       the name of that address, if it exists
       doesn't make sense to be used externally...'''
    st = str(st)
    m = map(lambda x:int(x,16),re.findall(r"(?<=0x)[0-9a-f]+",st))
    for val in m:
      if self[val]['name']:
        st = st.replace(hex(val),self[val]['name'])
    return st

  # keep the old tags interface
  # names and function data no longer stored here
  # things like xrefs can go here
  # only write functional tags here
  # comment     -- comment on this address
  # len         -- number of bytes grouped with this one
  # instruction -- string of this instruction
  # type        -- unset, 'instruction', 'data', 'string'
  def get_tags(self, filt, addresses=None):
    ret = {}
    if addresses == None:
      # all the addresses
      addresses = self.tags.keys()
    for a in addresses:
      rret = {}
      for f in filt:
        t = self[a][f]
        if t != None:
          rret[f] = t
      if rret != {}:
        ret[a] = rret
    return ret
  
  def __setitem__(self, address, dat):
    if type(address) is str:
      self.global_tags[address] = dat

  # for a single address
  def __getitem__(self, address):
    if type(address) is str:
      if address in self.global_tags:
        return self.global_tags[address]
      else:
        return None
    if address not in self.tags:
      self.tags[address] = Tags(self, address)
    return self.tags[address]

  # return the memory at address:ln
  # replaces get_static_bytes
  # TODO: refactor this! 
  def memory(self, address, ln):
    dat = []
    for i in range(ln): # 0~15 -yuike
      ri = address+i

      # hack for "RuntimeError: dictionary changed size during iteration"
      # base_memory には，読み込んだバイナリの先頭と最後のアドレスが格納されている
      for (ss, se) in self.base_memory.keys():
        # アドレス範囲の判定(プログラム全体のアドレス内かどうか見ている)
        # ss = start_adress, se = end_address
        if ss <= ri and ri < se:
          try:
            # [address, address+ln] の範囲のバイナリを取得
            dat.append(self.base_memory[(ss,se)][ri-ss])
            #print "dat = ", repr(dat)
            break
          except:
            return ''.join(dat)
    #print "0x%0x-0x%0x" % (ss, se)
    return ''.join(dat)


  # add yuike
  # return the memory at address:ln
  # replaces get_static_bytes
  # TODO: refactor this! 
  def my_memory(self, address, ln):

    dat = []
    for i in range(ln): # 0~15 -yuike
      ri = address+i

      # hack for "RuntimeError: dictionary changed size during iteration"
      # base_memory には，読み込んだバイナリの先頭と最後のアドレスが格納されている
      for (ss, se) in self.base_memory.keys():
        # アドレス範囲の判定(プログラム全体のアドレス内かどうか見ている)
        # ss = start_adress, se = end_address
        if ss <= ri and ri < se:
          try:
            # [address, address+ln] の範囲のバイナリを取得
            dat.append(self.base_memory[(ss,se)][ri-ss])
            #print "dat = ", repr(dat)
            break
          except:
            return (''.join(dat), f)

    for k, v in self.traces.items():
      if v == ss:
        f = open("/tmp/qira_logs/" + k + "_trace_asm", 'a')
        f.write(hex(address-ss) + ":")
        f.close()
        break
    #print "0x%0x-0x%0x" % (ss, se)
    return (''.join(dat), k)

  # 読み込んだライブラリの先頭と終わりのアドレスに，本体バイナリを対応させている
  # -yuike
  def my_add_memory_chunk(self, address, dat, file_name):
    f_name = file_name.split("/")[-1]
    if f_name not in self.traces:
      self.traces[f_name] = address
      
    #for k, v in self.traces.items():
    #  print "%s: 0x%0x" % (k, v)
    #print "add segment",hex(address),len(dat)
    """
    i = 0
    print "\n"
    for (ss, se) in self.base_memory.keys():
      print "0x%0x-0x%0x" % (ss, se)
      i += 1
    print "i = %d\n" % i
    """
    # check for dups
    for (laddress, llength) in self.base_memory:
      if address == laddress:
        if self.base_memory[(laddress, llength)] != dat:
          print "*** WARNING, changing segment",hex(laddress),llength
        return

    # segments should have an idea of segment permission
    self['segments'].append((address, len(dat)))
    # 本体バイナリを対応付け
    self.base_memory[(address, address+len(dat))] = dat

  def add_memory_chunk(self, address, dat):
    #print "add segment",hex(address),len(dat)
    # check for dups
    for (laddress, llength) in self.base_memory:
      if address == laddress:
        if self.base_memory[(laddress, llength)] != dat:
          print "*** WARNING, changing segment",hex(laddress),llength
        return

    # segments should have an idea of segment permission
    self['segments'].append((address, len(dat)))
    self.base_memory[(address, address+len(dat))] = dat

  def process(self):
    self.analyzer.analyze_functions(self)
    if self.debug >= 1:
      print "*** found %d functions" % len(self['functions'])


# *** STATIC TEST STUFF ***

if __name__ == "__main__":
  static = Static(sys.argv[1],debug=1)
  print "arch:",static['arch']

  # find main
  static.process()
  """
  main = static.get_address_by_name("main")
  print "main is at", main
  recursive.make_function_at(static, static['entry'])
  print "found %d functions" % len(static['functions'])
  recursive.make_function_at(static, main)
  print "found %d functions" % len(static['functions'])
  """


  # function printer
  for f in sorted(static['functions']):
    print static[f.start]['name'] or hex(f.start), f
    for b in sorted(f.blocks):
      print "  ",b
      for a in sorted(b.addresses):
        print "    ",hex(a),static._insert_names(static[a]['instruction'])


  # print symbols
  print "symbols"
  names = static.get_tags(['name'])
  for addr in names:
    print "%8x: %s" % (addr, names[addr]['name'])

  #print static['functions']

  #print static[main]['instruction'], map(hex, static[main]['crefs'])
  #print static.get_tags(['name'])
  #bw_functions = byteweight.fsi(static)
  #for f in bw_functions:
    #print hex(f)
    #hexdump(static.memory(f, 0x20))


