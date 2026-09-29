; Alas desktop installer (NSIS).
;
; Layout produced by the release workflow (see deploy/packaging/README.md):
;   dist/Alas/Alas.exe            <- the launcher (GUI subsystem)
;   dist/alas-backend/           <- the PyInstaller onedir sidecar
;
; Design decisions that matter for the updater:
;   - no admin rights: everything lands in $LOCALAPPDATA\Programs\Alas, so
;     `/S` silent upgrades work without UAC and cannot fail on a locked
;     Program Files.
;   - user data (config/, log/, assets/, bin/, user updates) lives in
;     %LOCALAPPDATA%\Alas, NOT next to the program: an upgrade replaces the
;     program directory wholesale and must not touch anything the user owns.
;   - `SetShellVarContext current` so $LOCALAPPDATA resolves per-user.
;   - the uninstaller removes the program directory and leaves the data
;     directory alone (with a prompt in interactive mode).
;
; Build (from the repo root):
;   uv run python dev_tools/gen_app_icon.py          # build/alas.ico
;   makensis /DVERSION=v2026.10.01 deploy/packaging/alas_installer.nsi
;
; The icon is a build product (NSIS only takes .ico, the SPA ships a PNG),
; so generate it before makensis.

!ifndef VERSION
  !define VERSION "dev"
!endif
!ifndef OUTFILE
  !define OUTFILE "Alas_${VERSION}_x64-setup.exe"
!endif

!define PUBLISHER "Joxos"
!define APPNAME "Alas"
!define REGKEY "Software\${APPNAME}"
!define DATADIR "$LOCALAPPDATA\${APPNAME}"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey "${REGKEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Unicode true
SetShellVarContext current

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} desktop app"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" "GPL-3.0"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON "build\alas.ico"
!define MUI_UNICON "build\alas.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Alas\Alas.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

Section "Install"
  ; The running app holds its files open; ask it to exit first. Silent
  ; upgrades rely on this too (the updater runs `/S /R`).
  nsExec::ExecToLog '"$INSTDIR\Alas\Alas.exe" --quit'
  Sleep 1200

  SetOutPath "$INSTDIR"
  File /r "dist\Alas"
  SetOutPath "$INSTDIR"
  File /r "dist\alas-backend"

  ; version.txt is what the app shows as "current version" and what the
  ; updater compares against; the workflow writes it into the sidecar dir.
  WriteRegStr "${REGKEY}" "Version" "${VERSION}"
  WriteRegStr "${REGKEY}" "InstallDir" "$INSTDIR"

  CreateDirectory "${DATADIR}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\Alas\Alas.exe"
  CreateShortCut "$SMPROGRAMS\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall ${APPNAME}.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\Alas\Alas.exe"
  WriteUninstaller "$INSTDIR\Uninstall ${APPNAME}.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\Uninstall ${APPNAME}.lnk"
  RMDir /r "$INSTDIR\Alas"
  RMDir /r "$INSTDIR\alas-backend"
  Delete "$INSTDIR\Uninstall ${APPNAME}.exe"
  RMDir "$INSTDIR"
  DeleteRegKey "${REGKEY}"

  ; The data directory is the user's: configs, logs, downloaded assets, bot
  ; state. Interactive uninstalls offer to remove it; silent ones keep it.
  IfSilent +2
  MessageBox MB_YESNO|MB_ICONQUESTION "Remove ${APPNAME} data as well?$n$nt(config, log, assets, bin - this cannot be undone)" \
    IDYES RemoveData
  Goto Done
  RemoveData:
    RMDir /r "${DATADIR}"
  Done:
SectionEnd
