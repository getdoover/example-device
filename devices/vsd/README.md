# Example VSD

This example represents a 7.5 kW Schneider pump drive with Start, Stop, and a
0–50 Hz frequency setpoint. Its UI follows the Ring Tank VSD on the reference
Pump Station. All telemetry and operating history are synthetic. The display
app stays stopped; only the example processor runs.

## Operating history

The dataset covers 90 days before installation midnight and 30 days after it.
It contains 3,099 telemetry samples and 390 historical commands. Each command
has an RPC record and an activity log. Starts, stops, and setpoint changes use
the same Python model as live playback.

Historical runs start between 06:00 and 08:00, increase frequency at 11:00,
reduce it at 15:00, and stop between 18:00 and 19:00. Every seventh day is idle.
Older samples use the water-storage spacing: six hours before day -45, two
hours until day -14, then 30 minutes. Extra samples preserve command times and
recent speed ramps.

The installation starts stopped with the final historical frequency selected.
Future sample times are 30 minutes apart. Their values are calculated by
`model.py` during playback. Live commands take precedence indefinitely within
the 30-day timeline; there are no scripted future commands.

## Model behaviour

The model ramps frequency at 1 Hz per second. Power follows an illustrative
centrifugal-pump curve, `7.5 × (frequency / 50)³` kW. Motor output voltage
follows frequency. Mains voltage stays close to 415 V while the motor is stopped.
The flow switch closes at 15 Hz. Drive thermal load approaches an operating
target gradually and cools toward 20% after stopping. These are demo profiles,
not equipment ratings or a motor-sizing calculation.

Running hours include deceleration and stop accumulating at zero speed. Energy
integrates the power curve across each speed ramp. Analytic calculations make
these totals independent of the number of processor invocations.

Each accepted command stores its model checkpoint before publishing an input
log, a telemetry transition, and the acknowledgement. The next scheduled minute
updates the ramp. While viewed, current values update every minute. Otherwise,
normal updates use the processor's 30-minute interval. Regular telemetry history
remains on the dataset's sample times, with extra records at live commands.

Late commands take effect after the last reserved playback time. Their RPC
response includes `effective_at_ms`. This preserves samples whose writes may
already have succeeded. Older command IDs are superseded across the model's
controls, including a late Start after a newer Stop. Retries reuse the saved
effective time and message IDs. Historical RPC imports never execute commands.

At day +30, playback stops and new model commands return an error. Existing
examples without a model retain their acknowledgement-only behaviour.

## Python model trust

The processor downloads `model.py` from the same full Git commit as the dataset.
The display app declares it in `config.example_model`, so existing organisation
installers can still validate the dataset manifest without a schema upgrade.
It permits executable models only from `getdoover/example-device`. It compares
the dataset's model name and SHA-256 with the processor-owned allowlist in
`src/example_device/models.py`, then checks the downloaded bytes before compiling
or executing them. Dataset metadata cannot approve new Python code.

Downloads use HTTPS without credentials or redirects, with a 30-second timeout
and a 64 KiB model limit. Each load gets a fresh module namespace. Per-device
state and commands are JSON checkpoints, not module globals. The model returns
scalar telemetry under its declared app; the processor validates the result and
owns channel writes.

This is trusted Python execution, not a sandbox. Approved code has the
processor's permissions. Do not approve customer-supplied Python without review.
The existing device lock is best-effort; this change does not provide strict
cross-invocation consistency.

API version 1 exports `validate(state, commands)`,
`command(commands, method, value)`, and `step(state, commands, elapsed_seconds)`.
The last function returns the new state and telemetry. It must be deterministic,
have no external side effects, and produce equivalent state across different
tick intervals. The runtime resumes from command checkpoints and prunes older
checkpoints after forward publication succeeds.

## Generate and verify locally

Run these commands from the repository root:

```sh
uv sync --frozen
uv run python tools/generate_vsd.py
uv run example-device validate devices/vsd
uv run python tools/simulate_vsd.py
uv run pytest tests/test_models.py -q
```

The simulator exercises Start, Stop, frequency changes while running and stopped,
and reloads the dataset and runtime between every step. It writes actual
observations to `build/vsd/command-demo.json`. These commands make no cloud writes.

## Release a model update

1. Edit and review `model.py`. Format the file before calculating its hash.
2. Calculate its SHA-256 with `shasum -a 256 devices/vsd/model.py`.
3. Add the reviewed model name and digest to the processor allowlist. Use a new
   model name for a new release and retain approvals required by existing devices.
4. Update the generator's model name, regenerate the dataset, and run the tests.
5. Publish the processor release containing the new approval and the dataset
   commit. Provision a `vsd` example using that full commit and its midnight anchor.

Changing Python bytes requires a processor approval release with this initial
allowlist design. New datasets using already approved model bytes do not.
Existing installations remain pinned to their original dataset and model.
Device creation and app installation remain the responsibility of provisioning.
