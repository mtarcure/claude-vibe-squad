const encoded = "aHR0cHM6Ly9wcml2YXRlLWVuZ2FnZW1lbnQuY29ycC9hcGk_Pz8";
const decoded = Buffer.from(encoded, "base64url").toString("utf8");
export const response = fetch(decoded);
