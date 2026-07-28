const concatUrl = "https://api".concat(".example.com/status");
const replaceUrl = "https://placeholder.example.com/status".replace("placeholder", "api");
const repeatUrl = "https://".concat("a".repeat(3), ".example.com/status");
const decodedUrl = atob("aHR0cHM6Ly9hcGkuZXhhbXBsZS5jb20vc3RhdHVz");
const escapedUrl = decodeURIComponent("https%3A%2F%2Fapi.example.com%2Fstatus");
const spreadParts = ["https://", ...["api", ".example.com/status"]];

export const responses = [
  fetch(concatUrl),
  fetch(replaceUrl),
  fetch(repeatUrl),
  fetch(decodedUrl),
  fetch(escapedUrl),
  fetch(spreadParts.join("")),
];
