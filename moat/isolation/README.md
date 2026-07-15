# Mac isolation profile

These files are declarative Phase-1 inputs. They do not provision, start, or probe a container.

The supported host path is macOS → Colima, Lima, or Docker Desktop → Linux container. A single-process lab uses `--network none` and places its loopback oracle in the same container. A multi-process lab uses a dedicated internal network plus every negative canary in `negative-canaries.json`; an internal bridge alone is not proof of isolation.

Before any future L3 run, the loopback control must succeed and every external canary must fail. Unexpected DNS, IPv4, IPv6, proxy, host-gateway, TCP, or TLS success aborts the run. The later runner must also enforce the non-root, no-socket, read-only-root, dropped-capability, mount, and resource-limit values from the profile.

Native macOS `pf` is not the default and requires separately reviewed setup and teardown.
