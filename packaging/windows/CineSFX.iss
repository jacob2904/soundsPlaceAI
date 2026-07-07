; Inno Setup script for the CineSFX Windows installer (setup .exe).
; Build with: iscc packaging\windows\CineSFX.iss  (after staging the payload).
; See packaging\build_exe.ps1 for the full one-command build.

#define AppName "CineSFX"
#define AppVersion "0.1.0"
#define AppPublisher "soundsPlaceAI"
#define PluginId "com.soundsplaceai.cinesfx"

[Setup]
AppId={{9C6F7B2E-CDE1-4E7B-9E2A-CINESFX000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Install straight into Resolve's Workflow Integration Plugins folder.
DefaultDirName={commonappdata}\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\{#PluginId}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\..\build
OutputBaseFilename=CineSFX-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}

[Files]
; The staged, self-contained payload (build\payload) becomes the plugin folder.
Source: "..\..\build\payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Messages]
FinishedLabel=CineSFX was installed. Start DaVinci Resolve and open Workspace > Workflow Integrations > CineSFX AI.

[Run]
; Nothing to run — Resolve loads the plugin on next launch.
