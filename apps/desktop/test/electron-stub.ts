import os from "node:os";

export const app = {
  getPath: (): string => process.env.VESTA_TEST_USER_DATA ?? os.tmpdir(),
};
