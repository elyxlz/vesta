const ERROR_MAP: [RegExp, string][] = [
  [/reboot/i, "restart your computer to finish setup, then reopen vesta."],
  [
    /wsl.*not installed/i,
    "WSL2 is required but not installed. Open PowerShell as Admin and run: wsl --install",
  ],
  [
    /wsl.*(virtualization|bios)/i,
    "virtualization needs to be enabled in your BIOS settings.",
  ],
  [/wsl.*failed/i, "WSL2 installation failed. Try running: wsl --install"],
  [
    /rootfs.*download/i,
    "couldn't download vesta. check your internet connection and try again.",
  ],
  [
    /services did not start/i,
    "services didn't start in time. try closing vesta and reopening it.",
  ],
  [
    /docker.*not installed/i,
    "docker is required but not installed. please install docker desktop.",
  ],
  [
    /docker.*(daemon|not running)/i,
    "docker isn't running. start docker desktop and try again.",
  ],
  [
    /failed to pull/i,
    "couldn't download. check your internet connection and try again.",
  ],
  [
    /failed to run cli/i,
    "something went wrong starting vesta. try reinstalling.",
  ],
  [/setup[_-]?token/i, "authentication setup failed. try again or reinstall."],
];

export function friendlyError(raw: string): string {
  for (const [pattern, friendly] of ERROR_MAP) {
    if (pattern.test(raw)) return friendly;
  }
  return raw;
}
