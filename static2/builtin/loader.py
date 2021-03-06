# coding: utf-8

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.relocation import RelocationSection
from elftools.common.exceptions import ELFError
import struct

def get_arch(fb):
  if fb == 0x28:
    return 'arm'
  elif fb == 0xb7:
    return 'aarch64'
  elif fb == 0x3e:
    return 'x86-64'
  elif fb == 0x03:
    return 'i386'
  elif fb == 0x08:
    return 'mipsel'
  elif fb == 0x1400:   # big endian...
    return 'ppc'
  elif fb == 0x800:
    return 'mips'

# 解析対象バイナリをロードする処理 -yuike
def load_binary(static):
  print "load_binary", static.path # -yuike
  try:
    # バイナリの読込み
    elf = ELFFile(open(static.path))
  except ELFError:
    print "*** loader error: non-ELF detected"
    return

  # TODO: replace with elf['e_machine']
  # アーキテクチャの判定
  progdat = open(static.path).read(0x20)
  fb = struct.unpack("H", progdat[0x12:0x14])[0]   # e_machine
  static['arch'] = get_arch(fb)
  static['entry'] = elf['e_entry'] # エントリポイントの取得
  print "entry_point = 0x%0x" % static['entry']

  ncount = 0
  # プログラムヘッダ (セグメント) の解析
  for segment in elf.iter_segments():
    addr = segment['p_vaddr']
    if segment['p_type'] == 'PT_LOAD':
      memsize = segment['p_memsz']
      print "memsize = 0x%0x" % memsize
      static.add_memory_chunk(addr, segment.data().ljust(memsize, "\x00"))

  # セクションの解析
  for section in elf.iter_sections():
    if static.debug >= 1:
      print "** found section", section.name, type(section)

    if isinstance(section, RelocationSection):
      symtable = elf.get_section(section['sh_link'])
      if symtable.is_null():
        continue

      for rel in section.iter_relocations():
        symbol = symtable.get_symbol(rel['r_info_sym'])
        if static.debug >= 1: #suppress output for testing
          print "Relocation",rel, symbol.name
        if rel['r_offset'] != 0 and symbol.name != "":
          static[rel['r_offset']]['name'] = "__"+symbol.name
          ncount += 1

      # hacks for PLT
      # TODO: this is fucking terrible
      # PLT の関数を取得
      if section.name == '.rel.plt' or section.name == '.rela.plt':
        # first symbol is blank
        plt_symbols = []
        for rel in section.iter_relocations():
          symbol = symtable.get_symbol(rel['r_info_sym'])
          plt_symbols.append(symbol.name) # シンボルの取得

        # does this change?
        PLT_ENTRY_SIZE = 0x10

        for section in elf.iter_sections():
          if section.name == ".plt":
            for name, addr in zip(plt_symbols,
                     range(section['sh_addr'] + PLT_ENTRY_SIZE,
                           section['sh_addr'] + PLT_ENTRY_SIZE + PLT_ENTRY_SIZE*len(plt_symbols),
                           PLT_ENTRY_SIZE)):
              static[addr]['name'] = name
            #print plt_symbols, section['sh_addr']


    if isinstance(section, SymbolTableSection):
      for nsym, symbol in enumerate(section.iter_symbols()):
        #print symbol['st_info'], symbol.name, hex(symbol['st_value'])
        if symbol['st_value'] != 0 and symbol.name != "" and symbol['st_info']['type'] == "STT_FUNC":
          if static.debug >= 1:
            print "Symbol",hex(symbol['st_value']), symbol.name
          static[symbol['st_value']]['name'] = symbol.name
          ncount += 1

    # parse the DynamicSection to get the libraries
    #if isinstance(section, DynamicSection):
  if static.debug >= 1:
    print "** found %d names" % ncount

