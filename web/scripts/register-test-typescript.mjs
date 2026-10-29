import { register } from "node:module";

// Import only the shared configuration module: the package entry binds `screen`
// at load time, before each test file installs its JSDOM globals.
import { configure } from "@testing-library/dom/dist/config.js";

register("./test-typescript-loader.mjs", import.meta.url);

// Shared CI runners execute every test file concurrently. The default one-second
// find*/waitFor budget measures runner load rather than UI behavior, so allow a
// longer wait before reporting that an expected element never appeared.
configure({ asyncUtilTimeout: 10_000 });
