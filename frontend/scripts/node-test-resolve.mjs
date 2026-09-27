// Node запускает `.ts` сам (type stripping), но не угадывает расширение у
// импорта `./sourcePlaces` — Vite и tsc (moduleResolution: Bundler) угадывают.
// Этот хук добавляет `.ts`, чтобы юнит-тесты шли без сборщика.
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (error?.code !== "ERR_MODULE_NOT_FOUND" || !/^\.{1,2}\//.test(specifier)) throw error;
      return nextResolve(`${specifier}.ts`, context);
    }
  },
});
