"""Ask PRT itself which options its encoders take - measured, not guessed from docs.

PyPRT does not expose prt::createEncoderInfo, but the PRT core DLL it ships exports it, plus the
non-virtual prt::Object::toXMLDocument. ctypes calls both, and the XML is each encoder's full option
list with defaults and descriptions. Written to data/lab/register/encoder_options/<id>.xml.

  python scripts/lab_register_probe_encoders.py
"""
import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "register", "encoder_options")

IDS = ["com.esri.prt.codecs.GLTFEncoder", "com.esri.prt.unreal.encoder", "com.esri.prt.codecs.ColladaEncoder",
       "com.esri.prt.codecs.FBXEncoder", "com.esri.prt.codecs.USDEncoder", "com.esri.prt.codecs.I3SEncoder",
       "com.esri.prt.codecs.OBJEncoder", "com.esri.pyprt.PyEncoder"]


def main():
    import pyprt
    pyprt.initialize_prt()                      # loads the extension codecs into the process
    core = ctypes.WinDLL(os.path.join(os.path.dirname(pyprt.pyprt.__file__), "bin", "com.esri.prt.core.dll"))
    create = getattr(core, "?createEncoderInfo@prt@@YAPEBVEncoderInfo@1@PEB_WPEAW4Status@1@@Z")
    create.restype = ctypes.c_void_p
    create.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    toxml = getattr(core, "?toXMLDocument@Object@prt@@QEBAPEADPEADPEA_KPEAW4Status@2@@Z")
    toxml.restype = ctypes.c_void_p
    toxml.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int)]
    os.makedirs(OUT, exist_ok=True)
    for eid in IDS:
        st = ctypes.c_int(0)
        info = create(eid, ctypes.byref(st))
        if not info:
            print("  %-40s not available (status %d)" % (eid, st.value)); continue
        n = ctypes.c_size_t(1 << 20)
        buf = ctypes.create_string_buffer(n.value)
        toxml(info, buf, ctypes.byref(n), ctypes.byref(st))
        xml = buf.value.decode("utf-8", "replace")
        p = os.path.join(OUT, eid + ".xml")
        open(p, "w", encoding="utf-8").write(xml)
        print("  %-40s %6d bytes -> %s" % (eid, len(xml), os.path.relpath(p, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
