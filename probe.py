import sys
from jl import Display, find_port

print("port:", find_port())
d = Display()
d.prime()
info, raw = d.info()
print("raw reply:", raw.hex())
print("info:", info)
d.close()
