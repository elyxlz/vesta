export interface VerifyPackContext {
  electronPlatformName: string;
  appOutDir: string;
  packager: { appInfo: { productFilename: string } };
}

export default function verifyPack(context: VerifyPackContext): void;
