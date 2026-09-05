# Research Notes and Claim Audit

Prepared 2026-09-05. This is a focused background review, not an exhaustive
systematic review or evidence that no closer prior work exists. Searches covered
SDN microgrids, electrical reconfiguration, communication/power co-simulation,
cyber-physical testbeds, and official PSCAD automation and component behavior.
Only primary papers, author/institutional records, and official documentation
support the manuscript's technical background. No third-party figures or
verbatim literature passages are reproduced.

## Positioning

Working title: **Toward SDN-Controlled Microgrid Reconfiguration: An Auditable
Python-PSCAD Switching Testbed**.

The defensible present contribution is an inspectable integration workflow and
preliminary functional validation. SDN microgrid control is not a new concept.
The current implementation is a batch-driven, single-source LV feeder testbed
that can support later microgrid research. It is not yet a synchronized
communication/EMT federation or an always-connected hardware control plane.

## Verified Literature

The BibTeX keys below connect each source to its intended claim. DOI links in
`references.bib` are preferred publication locators; the primary reading links
here document what was available during background research. Missing page
ranges or DOIs were omitted rather than guessed.

| Key | Primary reading / verification | Use and boundary |
| --- | --- | --- |
| `baran1989` | [Original paper, university-hosted PDF](https://ecal.studentorg.berkeley.edu/tbsi/Energy-Systems-Optimization-Course/References/Baran89%20-%20UCB%20-%20DistFlow.pdf); [IEEE DOI](https://doi.org/10.1109/61.25627) | Classical radial feeder reconfiguration; not our implemented optimizer. The separate Power Engineering Review abstract has a different DOI and was not conflated with this paper. |
| `mckeown2008` | [Original OpenFlow paper, Stanford](https://web.stanford.edu/class/cs244/papers/openflow.pdf); [author publication list](https://yuba.stanford.edu/~nickm/papers.html) | Programmable control/forwarding separation. Does not establish packetized electrical power or a breaker protocol. |
| `doeMicrogrids` | [DOE Office of Electricity](https://www.energy.gov/oe/microgrid-systems) | Scope of a microgrid; motivates distinguishing the present feeder from DER/islanding capability. |
| `wang2020` | [Author paper in NSF repository](https://par.nsf.gov/servlets/purl/10181654); [author publication list](https://www.ece.stonybrook.edu/~pzhang/papera.html) | Software-defined microgrid control through virtualization. Journal 7, 173-182; DOI 10.1109/OAJPE.2020.2997665. Indexed primary PDF text and author metadata were used; direct retrieval was intermittently unavailable. |
| `li2021` | [Penn State institutional publication record and abstract](https://pure.psu.edu/en/publications/programmable-and-reconfigurable-cyber-physical-networked-microgri/) | Prior OpenFlow/SDN-enabled networked microgrid reconfiguration. Only abstract-level scope is summarized; no uninspected experimental details are claimed. |
| `dorsch2017` | [Author-hosted paper, TU Dortmund](https://cni.etit.tu-dortmund.de/storages/cni-etit/r/Research/Publications/2017/Dorsch_EI2/Dorsch_EI2_11_2017.pdf) | Actual communication-system comparison in distributed grid control, unlike our imposed timestamps. DOI is printed on the paper. |
| `ciraci2014` | [PNNL original publication record](https://www.pnnl.gov/publications/fncs-framework-power-system-and-communication-networks-co-simulation) | Federated power/communication simulation and synchronization. Article 36; no DOI guessed. |
| `palmintier2017` | [PNNL original publication record](https://www.pnnl.gov/publications/design-helics-high-performance-transmission-distribution-communication-market-co) | Coordinated simulator federation. Not a framework already integrated in this project. |
| `haque2025` | [Author-hosted IEEE Access paper, Texas A&M](https://katedavis.engr.tamu.edu/wp-content/uploads/sites/180/2025/07/Cyber-Physical_Emulation_and_Threat_Scenario_Simulation_for_Enhanced_Microgrid_Resilience.pdf) | Recent microgrid-derived cyber/power emulation with DNP3 and threat scenarios. No comparison of security performance to our system. DOI and pages verified in the paper. |
| `pscadAutomation` | [Official automation quick start](https://www.pscad.com/webhelp-v501-al/quick_start.html) | Python project loading/execution. Documentation version 2.8.4 is not the locally recorded installed version 2.9.7. Local code determines the exact project behavior. |
| `pscadTimedBreaker` | [Official timed breaker logic help](https://www.pscad.com/webhelp/Master_Library_Models/Breakers/timed_breaker_logic.htm) | One or two timed operations and breaker signal binding. The two-transition limit belongs to the selected mapping, not all possible PSCAD models. |
| `pscadFaults` | [Official fault overview](https://pscad.com/webhelp-v502-ol/Master_Library_Models/Breakers_And_Faults/Faults/Faults_Overview.htm) | Resistive-switch fault abstraction and lack of arc dynamics. Version 5.0.2 help supports generic model behavior; the saved local case is PSCAD 5.0.1. |

No long direct quotations were used. The text, architecture diagram, feeder
schematic, and plots were created for this manuscript. The source papers are
linked, not redistributed.

## Project Evidence

The clean inspected repository revision was
`7db42ae0e9f8092065cf77bb206b1a818c29eacd`. This is the revision observed at
snapshot time, not an assertion that every historical run was executed at this
exact commit. See `data/provenance.json` for the SHA-256 hashes of the actual
saved artifacts and source files read.

| Claim | Evidence | Wording limit |
| --- | --- | --- |
| Six working saved PSCAD conditions | `transient_scenario_results.json`, six scenario inputs | One saved deterministic result per condition, not repeated stochastic trials. |
| Native three-phase fault and restoration | S6 fault manifest, channel summaries and intervals | Fault and controller times are supplied inputs; no implemented relay detection is established. |
| 1.554 kA largest phase peak | S6 `measured_metrics.fault_current_peak_abs_ka` | Saved full-rate maximum, not a peak recovered from the preview. |
| Approximately 1.195 s downstream interruption | S6 full-rate threshold intervals | Experimental 200-V threshold and filtering, not standards compliance. |
| 39 s extra waiting in S5 versus S3 | Input times 45 versus 6 s, interval differences | Imposed delay; no measured SDN versus legacy latency. |
| Dashboard changes invoke PSCAD | Recorded graphical GUI summary and command-edit timeline | Prior saved integration check; no new GUI run for this manuscript. |
| Loop closure rejected | S4 one issued / zero accepted commands, zero events | Does not establish all-or-nothing rejection of arbitrary mixed commands. |
| 114 tests passed | Existing `AI_CONTEXT.md` recorded test report | Historical context statement only; tests were not rerun here. |
| Electrical R/L/load values | Saved build report and `build_lv_feeder.py` | Illustrative settings, not measured cable, transformer, or load calibration. |

The preparation script validates internal consistency of saved results. It
does not independently recompute full-rate extrema from raw `.psout` files,
which are not bundled per scenario in this paper package.

## Important Findings from Read-Only Code Inspection

1. `LOAD_PF = 0.98` multiplies target demand in a resistance calculation. It
   does not enforce a 0.98 electrical power factor. The manuscript reports
   resistive loads and their nominal-voltage effective demands.
2. `PowerPlaneState.apply_command()` records warnings and then applies
   individual requests. A partially invalid command can still change some
   edges. The paper explicitly avoids describing this as atomic safety
   validation or a transactional interlock. No fix was made, in accordance
   with the instruction not to touch the working project.
3. `State_*` channels record controller signals, not independently measured
   breaker contacts. The diagram's schedule panel is explicitly an input plot.
4. Each dashboard commit triggers a fresh batch experiment. A persistent MCP
   connection does not provide live solver feedback, time synchronization, or
   an always-powered physical communications network.
5. Output cleanup intentionally replaces the current case's raw result. A
   publication experiment campaign must archive raw outputs under distinct
   names before rerunning.
6. No-event line schedules use a transition after the run window. The current
   `tbreakn` binding supports at most two transitions per breaker per run.
7. Scenario text saying protection "detects" the fault describes intent,
   not an implemented relay. Only S6 applies a native electrical fault;
   S2 and S3 are commanded isolation cases.
8. The 0.2-kV interruption threshold uses a 0.5-s startup exclusion, merges gaps
   of at most 0.02 s, and discards intervals shorter than 0.01 s. Ongoing
   intervals are right-censored. These are not customer reliability metrics.

## Submission Checklist

- [ ] Confirm author order, affiliations, contact details, and networking-team credit.
- [ ] Select a venue and articulate a contribution appropriate to its novelty criteria.
- [ ] Broaden the literature search for the selected venue; this was a focused review.
- [ ] Calibrate source, cables, transformer, neutral/ground, loads, and fault levels.
- [ ] Correct or rename the misleading load-sizing parameter in a separately authorized code task.
- [ ] Add atomic prospective validation and independent electrical safety constraints.
- [ ] Agree the controller transport, schema versions, acknowledgment, replay, and failure policy.
- [ ] Add measured fault detection and causally synchronized controller feedback for closed-loop claims.
- [ ] Compare against fixed/manual and updated network policies on identical electrical inputs.
- [ ] Sweep fault resistance, location, switching delay, loading, and numerical time step.
- [ ] Run repeated seeded communication trials before claiming latency or reliability improvements.
- [ ] Archive each raw `.psout`, complete case/library settings, manifests, logs, and environment lock.
- [ ] Generate full-rate transient figures directly from archived raw outputs.
- [ ] Review all prose after a snapshot refresh; tables update automatically, prose does not.
- [ ] Confirm funding, acknowledgments, conflicts, software/data permissions, and release location.
- [ ] Check the target venue's AI-assistance disclosure requirements with the authors.

## Preparation Boundary

All changes for this task are confined to `research_paper/`. Existing code,
PSCAD cases, generated simulator outputs, tests, and `AI_CONTEXT.md` were only
read. No simulator, server, or GUI automation was started for manuscript
preparation. Compiling the paper uses the installed TeX toolchain; its ordinary
user-level font/cache access is separate from the operational project.
