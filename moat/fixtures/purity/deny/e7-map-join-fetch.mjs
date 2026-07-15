const endpoint = ["https://private", "engagement.corp", "status"]
  .map((part) => part)
  .join("/");
export const response = fetch(endpoint);
