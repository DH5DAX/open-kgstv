Open KG-STV @VERSION@ - @TARGET@

Unsigned preview build. Unpack the archive into a folder you own.
Windows: double-click OpenKGSTV.exe. No Python installation is required.
Linux / Raspberry Pi OS: run ./OpenKGSTV from a graphical desktop session.
If necessary: chmod +x OpenKGSTV
The ARM64 build requires a 64-bit operating system (aarch64); it does not run
on 32-bit Raspberry Pi OS. Linux baseline: Debian 12 / glibc 2.36 or newer.
Keep the README and licence notices with the application when redistributing.

Linux desktop libraries: X11/XWayland, fontconfig, ALSA, libGLib and the usual
Tcl/Tk graphical dependencies. Python, Tcl/Tk and PortAudio are bundled.
The program needs a writable temporary directory supporting executable files
and symbolic links for one-file extraction.

Radio CAT support uses a separately installed Hamlib rigctld, or a rigctld
server on your network. On Debian/Raspberry Pi OS: apt install libhamlib-utils
On Windows, use the official Hamlib x64 archive and select rigctld.exe in Setup.
An optional portable Hamlib installation in hamlib/bin next to OpenKGSTV is
also detected. Radio USB drivers and OS permissions remain system settings.

No radio or audio stream opens at startup. Configure your USB audio devices
and radio with the small setup gear, then explicitly start receiving/sending.
Settings, gallery and logbook are saved in the user's normal OpenKGSTV data
directory, not inside the executable or its temporary extraction directory.
EN / DE switches the interface language immediately.

This is an unsigned, experimental build. Full interoperability with the
original KG-STV is still being verified; physical IC-7610 testing is pending.

Source, documentation and downloads:
https://github.com/DH5DAX/open-kgstv
Build instructions: packaging/BUILDING.md in the source repository.
build-info.json records architecture, dependency versions and offline tests.

Deutsch: Archiv entpacken und OpenKGSTV starten; Python ist nicht erforderlich.
Die Raspberry-Version benoetigt ein 64-Bit-Betriebssystem mit Desktop.
CAT-Steuerung verwendet eine separate Hamlib-Installation oder einen
rigctld-Server. Funkgeraet und Audio werden ueber das Zahnrad eingerichtet.
Diese Vorschau ist unsigniert und noch nicht vollstaendig kompatibilitaetsgeprueft.
