const prefix = `private`;
const suffix = `${"engagement"}.corp`;
export const response = fetch(`https://${prefix}-${suffix}/status`);
