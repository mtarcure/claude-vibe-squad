function evaluate(fixture) {
  if (!fixture || typeof fixture !== "object" || !fixture.observation) {
    throw new TypeError("external fixture must contain an observation");
  }
  const violation = fixture.observation.protected_transition === true
    && fixture.observation.trusted_marker !== true;
  return {
    violation,
    expected_violation: fixture.expected_violation,
    calibrated: violation === fixture.expected_violation,
  };
}

export function runOracle(positiveFixture, negativeFixture) {
  const positive = evaluate(positiveFixture);
  const negative = evaluate(negativeFixture);
  return {
    positive,
    negative,
    calibrated: positive.calibrated && negative.calibrated
      && positive.violation && !negative.violation,
  };
}
