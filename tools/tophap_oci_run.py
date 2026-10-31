"""OCI Run Command helper for the production VM (miao-prod-a1).

Usage: oci_run.py <script-file> <out-prefix> [timeout_seconds]

Creates an Instance Agent Command (TEXT source), polls the execution
until a terminal state, and writes the full result to
<out-prefix>.json plus the plain command output to <out-prefix>.out.
Credentials come from ~/.oci/config only; nothing secret is printed.

Per ops notes (2026-10-14/17): commands execute as user `ocarun`;
ACCEPTED may sit for minutes (pickup jitter is normal); the text
output lives in `.content.text` on SDK 2.187 (`.output` stays empty),
so both fields are read.
"""
import json
import sys
import time

import oci

INSTANCE_ID = (
    "ocid1.instance.oc1.iad.anuwcljr7nklamicii3r4m4xsvvtpaldkge2hf5ifmhuxvs3ny7z7ird5x6q"
)
COMPARTMENT_ID = (
    "ocid1.compartment.oc1..aaaaaaaam6cye5hw4ff6znkn62fkt4oehjlgzkslj753j4jytfqmvfnoeqna"
)
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELED"}


def main() -> int:
    script_path, out_prefix = sys.argv[1], sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    with open(script_path, encoding="utf-8") as fh:
        script = fh.read()

    config = oci.config.from_file("~/.oci/config")
    client = oci.compute_instance_agent.ComputeInstanceAgentClient(
        config, timeout=90
    )
    models = oci.compute_instance_agent.models

    display_name = f"tophap-{out_prefix.rsplit('/', 1)[-1]}"
    details = models.CreateInstanceAgentCommandDetails(
        compartment_id=COMPARTMENT_ID,
        execution_time_out_in_seconds=timeout,
        target=models.InstanceAgentCommandTarget(instance_id=INSTANCE_ID),
        content=models.InstanceAgentCommandContent(
            source=models.InstanceAgentCommandSourceViaTextDetails(
                source_type="TEXT", text=script
            ),
            output=models.InstanceAgentCommandOutputViaTextDetails(
                output_type="TEXT"
            ),
        ),
        display_name=display_name,
    )
    # The egress proxy intermittently stalls OCI API calls; a create
    # that times out may or may not have landed server-side. Before
    # each retry, list recent commands and adopt a same-named one
    # instead of blindly duplicating (matters for mutating scripts).
    import os
    cmd = None
    skip_adopt = os.environ.get("OCI_RUN_SKIP_ADOPT") == "1"
    for attempt in range(10):
        try:
            recent = [] if skip_adopt else client.list_instance_agent_commands(
                COMPARTMENT_ID,
                limit=20,
                sort_by="TIMECREATED",
                sort_order="DESC",
            ).data
            for item in recent:
                tgt = getattr(item, "target", None)
                tgt_id = getattr(tgt, "instance_id", None)
                if (
                    item.display_name == display_name
                    and tgt_id == INSTANCE_ID
                    and item.lifecycle_state in ("ACCEPTED", "IN_PROGRESS")
                ):
                    cmd = item
                    print(
                        f"adopting existing command_id={cmd.id} "
                        f"(attempt {attempt})",
                        flush=True,
                    )
                    break
            if cmd is not None:
                break
            cmd = client.create_instance_agent_command(details).data
            break
        except Exception as exc:  # noqa: BLE001
            print(f"create attempt {attempt} failed: {exc}", flush=True)
            time.sleep(20)
    if cmd is None:
        print("CREATE FAILED after retries", flush=True)
        return 4
    print(f"command_id={cmd.id}", flush=True)

    deadline = time.time() + timeout + 900  # pickup jitter allowance
    last_state = None
    while time.time() < deadline:
        ex = client.get_instance_agent_command_execution(
            cmd.id, INSTANCE_ID
        ).data
        state = ex.lifecycle_state
        if state != last_state:
            print(f"state={state}", flush=True)
            last_state = state
        if state in TERMINAL:
            content = ex.content
            text = getattr(content, "text", None)
            legacy = getattr(content, "output", None)
            payload = {
                "command_id": cmd.id,
                "lifecycle_state": state,
                "exit_code": getattr(content, "exit_code", None),
                "text": text,
                "output_legacy": legacy,
                "time_created": str(getattr(ex, "time_created", "")),
                "time_updated": str(getattr(ex, "time_updated", "")),
            }
            with open(f"{out_prefix}.json", "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            with open(f"{out_prefix}.out", "w", encoding="utf-8") as fh:
                fh.write(text if text is not None else (legacy or ""))
            print(f"terminal state={state} exit_code={payload['exit_code']}")
            return 0 if state == "SUCCEEDED" else 2
        time.sleep(15)
    print("POLL DEADLINE EXCEEDED", flush=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
