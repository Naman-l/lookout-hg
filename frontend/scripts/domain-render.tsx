// Entry for test-domain.mjs: renders the domain components to static markup inside a router (bundled with its own React).
import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import type { ReactNode } from "react";
export * from "../src/components/domain";
export const html = (node: ReactNode) => renderToStaticMarkup(<StaticRouter location="/">{node}</StaticRouter>);
export { createElement as h } from "react";
export { Match } from "../src/sections/inbox/Match";
