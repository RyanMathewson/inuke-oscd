$ErrorActionPreference = 'Stop'
Add-Type -Language CSharp @'
using System;
using System.Runtime.InteropServices;
namespace Au {
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ep);
  }
  [Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceCollection {
    int GetCount(out int n);
    int Item(int i, out IMMDevice dev);
  }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    int Activate(ref Guid iid, int clsCtx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
    int OpenPropertyStore(int access, out IPropertyStore store);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int state);
  }
  [Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {
    int GetCount(out int n);
    int GetAt(int i, out PROPERTYKEY key);
    int GetValue(ref PROPERTYKEY key, out PROPVARIANT v);
    int SetValue(ref PROPERTYKEY key, ref PROPVARIANT v);
    int Commit();
  }
  [StructLayout(LayoutKind.Sequential)] struct PROPERTYKEY { public Guid fmtid; public int pid; }
  [StructLayout(LayoutKind.Explicit)] struct PROPVARIANT {
    [FieldOffset(0)] public short vt;
    [FieldOffset(8)] public IntPtr p;
  }
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr n); int UnregisterControlChangeNotify(IntPtr n);
    int GetChannelCount(out int c);
    int SetMasterVolumeLevel(float d, ref Guid g);
    int SetMasterVolumeLevelScalar(float d, ref Guid g);
    int GetMasterVolumeLevel(out float d);
    int GetMasterVolumeLevelScalar(out float d);
  }
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
  public static class Mic {
    public static void Dump() {
      var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
      IMMDeviceCollection col; en.EnumAudioEndpoints(1, 1, out col);   // eCapture, ACTIVE
      int n; col.GetCount(out n);
      var NAME = new PROPERTYKEY(); NAME.fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"); NAME.pid = 14;
      for (int i = 0; i < n; i++) {
        IMMDevice d; col.Item(i, out d);
        string id; d.GetId(out id);
        IPropertyStore ps; d.OpenPropertyStore(0, out ps);
        PROPVARIANT pv; string name = "?";
        try { ps.GetValue(ref NAME, out pv); if (pv.p != IntPtr.Zero) name = Marshal.PtrToStringUni(pv.p); } catch {}
        var iid = typeof(IAudioEndpointVolume).GUID;
        object o; d.Activate(ref iid, 1, IntPtr.Zero, out o);
        var vol = (IAudioEndpointVolume)o;
        float scalar; vol.GetMasterVolumeLevelScalar(out scalar);
        Console.WriteLine("{0,-45} level = {1:F0}%", name, scalar * 100);
      }
    }
  }
}
'@
[Au.Mic]::Dump()
