import {
  type RouteConfig,
  index,
  layout,
  route,
} from "@react-router/dev/routes";

export default [
  // Public routes (no sidebar)
  route("/login", "routes/login.tsx"),

  // Protected routes (with sidebar)
  layout("components/app-layout.tsx", [
    index("routes/channels.tsx"),
    // route("/sources", "routes/sources.tsx"),
    // route("/users", "routes/users.tsx"),
    // route("/documents", "routes/documents.tsx"),
    // route("/settings", "routes/settings.tsx"),
    // route("/about", "routes/about.tsx"),
  ]),
] satisfies RouteConfig;
