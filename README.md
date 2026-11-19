# VLiP 2.0

**Docking, preparation, pose inspection and PLIP**  
**User guide for docking, receptor preparation, ligand preparation, pose inspection and PLIP analysis**  
Version covered: **VLiP 2.0.0 (Docking / PLIP release)**  
Platform: **Windows 10/11, 64-bit**

> This guide was prepared by inspecting the VLiP 2.0 source code. It documents the controls and workflows implemented in that version. It is not a claim that every possible installation, input structure or scientific result has been independently validated.

## Contents

1. [What VLiP does](#1-what-vlip-does)
2. [Installing and launching VLiP](#2-installing-and-launching-vlip)
3. [Quick start: dock an existing ligand and receptor](#3-quick-start-dock-an-existing-ligand-and-receptor)
4. [Understanding the main window](#4-understanding-the-main-window)
5. [Downloading and cleaning receptor structures](#5-downloading-and-cleaning-receptor-structures)
6. [Converting receptor PDB files to PDBQT](#6-converting-receptor-pdb-files-to-pdbqt)
7. [Preparing ligands from SMILES or structure files](#7-preparing-ligands-from-smiles-or-structure-files)
8. [Managing receptor and ligand queues](#8-managing-receptor-and-ligand-queues)
9. [Choosing a docking region](#9-choosing-a-docking-region)
10. [Configuring docking](#10-configuring-docking)
11. [Running, pausing, stopping and resuming](#11-running-pausing-stopping-and-resuming)
12. [Where the results are saved](#12-where-the-results-are-saved)
13. [Reading docking scores and PLIP interactions](#13-reading-docking-scores-and-plip-interactions)
14. [Using the built-in 3D viewer and PyMOL](#14-using-the-built-in-3d-viewer-and-pymol)
15. [Recent projects, comparison and HTML reports](#15-recent-projects-comparison-and-html-reports)
16. [Logs, audit trails and reproducibility](#16-logs-audit-trails-and-reproducibility)
17. [Troubleshooting](#17-troubleshooting)
18. [Scientific limitations and good practice](#18-scientific-limitations-and-good-practice)
19. [Frequently asked questions](#19-frequently-asked-questions)

---

## 1. What VLiP does

VLiP provides a graphical workflow around several molecular-modelling tools. In this release, it can:

- Download structures from the Protein Data Bank and clean a selected target using UniProt residue mappings.
- Prepare **rigid receptor PDBQT** files using PDB2PQR/PROPKA and Meeko.
- Prepare **ligand PDBQT** files from SMILES, SDF, MOL, MOL2, SMI, CSV or text inputs, with options for protonation, tautomers, stereochemistry and 3D conformers.
- Run **AutoDock Vina** against one or more receptors and ligands, with repeat docking jobs.
- Define a docking box over the whole receptor or over selected residues.
- Split Vina output into individual poses; optionally save merged receptor–ligand complexes and PDB files.
- Optionally run **PLIP** interaction analysis on docking poses.
- View structures and results with VLiP's built-in 3D viewer, and optionally open poses in PyMOL.
- Keep progress checkpoints, resume matching interrupted runs, inspect previous projects, compare projects and export HTML reports.
- Record software settings, executed commands and diagnostic logs.

**Important:** VLiP 2.0 is a **docking and PLIP** release. It does **not** contain the molecular-dynamics (MD) runtime or require WSL for MD. Docking scores are predictions, not experimental measurements.

### File types at a glance

| File | What it is used for |
| --- | --- |
| `.pdb`, `.cif`, `.mmcif` | Structural coordinates, including downloaded receptor structures. |
| `.pdbqt` | Receptor or ligand input for Vina; also Vina docking output. |
| `.smi`, `.smiles`, `.txt` | SMILES lists for ligand preparation. |
| `.sdf`, `.sd`, `.mol`, `.mol2` | Ligand structure files accepted by the ligand preparer. |
| `.csv` | Receptor panel import/export and ligand-list input where appropriate. |
| `.json` | Receptor panel definitions, preparation audit data, settings and run checkpoints. |
| `.html` | Shareable project report. |

## 2. Installing and launching VLiP

### 2.1 Start the program

For the packaged Windows release, extract the distribution and launch the supplied **VLiP 2.0 `.exe`**. Keep the executable in a normal writable directory. If using the single-file Python source instead, run it with a suitable Windows Python installation; **Python 3.12** is a sensible choice, and Tkinter must be available. The Python source itself contains the receptor/ligand tool interfaces; those tools do not need to be found as separate `.py` files.

A separate command-prompt window is not required for day-to-day use of a correctly packaged GUI executable.

### 2.2 Install the scientific tools

On first launch, VLiP checks its dependencies. If it reports missing components:

1. Click **Install / Repair ALL** under **Receptor Tools**, or open **Software Downloads → Install / Repair docking dependencies**.
2. Allow the installer to download and configure the scientific tools. An internet connection is needed for downloads.
3. Review the installation window and its saved setup log. Do not assume the setup succeeded just because the window closed.
4. After a successful install, use **Diagnose** to verify the setup.

The managed setup includes AutoDock Vina, a private Python 3.12 environment, PLIP, Open Babel, RDKit, Meeko, PDB2PQR, PROPKA, SciPy, Gemmi and supporting packages. The source specifies **Vina 1.2.7**, **PLIP 2.4.0** and **Meeko 0.7.1** for its managed installation. Installation and repair use a private directory instead of replacing your main Python setup.

Typical Windows managed location:

```text
%LOCALAPPDATA%\VLiP_2.0\
    tools\
    runtime\
    miniconda3\       (if a suitable Conda installation is unavailable)
    logs\
```

The installation log is saved under the managed `logs` directory with a filename beginning `setup_`.

**Optional PyMOL:** PyMOL is **not bundled**. Use **Software Downloads → Official PyMOL download** if you want to install it. The built-in 3D viewer works without PyMOL.

### 2.3 Check for problems

- **Diagnose** opens a software check and writes `vlip_diagnostics.txt` beside the VLiP program.
- **Setup info** describes the managed runtime and installed components.
- **Software Downloads** gives access to installation/repair, diagnostics and the PyMOL download page.
- If the preparation windows will not open, run **Install / Repair ALL**, then **Diagnose** again.

## 3. Quick start: dock an existing ligand and receptor

Use this route when you already have a **prepared receptor `.pdbqt`** and **prepared ligand `.pdbqt`**.

1. Launch VLiP and complete the dependency check.
2. Click **Select Output Folder** and choose an empty folder for the project, such as `D:\VLiP_Projects\Example_01`.
3. Under the receptor table, click **Add Files...** and select your receptor `.pdbqt`.
4. For a specific pocket, **double-click** the receptor row, change **Mode** to **Active**, and enter one or more receptor residue IDs. Alternatively, leave **Whole** selected for a box calculated from the entire receptor.
5. Click **Interactive 3D Preview** to check the selected region and box before committing to a run.
6. Click **Browse** beside **Ligand** to select one ligand `.pdbqt`, **or** use **Ligand Queue → Add Files...** to add several ligands.
7. Leave **Repeats** at `1` and **Exhaustiveness** at `8` for a first functional test. The source uses these as initial defaults; they are not universal scientific recommendations.
8. Optionally enable **Run PLIP interaction analysis**. Leave it off for a faster docking-only test.
9. Click **RUN DOCKING**. Read the **Check Before Docking** review carefully, then click **CONFIRM AND RUN**.
10. When finished, use **Open Results** to inspect scores and **View 3D Pose** to inspect poses.

The number of Vina jobs is:

```text
number of ligands × number of receptors × repeats
```

For example, two ligands, three receptors and two repeats produce **12 docking jobs**. PLIP may subsequently analyse multiple individual poses from each successful job.

If you start from a Protein Data Bank ID or a SMILES string instead, follow sections 5–7 before the quick-start docking steps.

## 4. Understanding the main window

### Main controls

| Control | Purpose |
| --- | --- |
| **Select Output Folder** | Choose where docking results, project state and reports will be written. |
| **Diagnose** | Check tools and save diagnostics. |
| **Software Downloads** | Installation/repair controls and optional PyMOL link. |
| **About the Developer** | Information about the VLiP project. |
| **Recent Projects** | Reopen previously recorded project folders. |
| **Open Results** | Browse results in a chosen VLiP project. |
| **Compare Projects** | Compare settings and docking scores between two projects. |
| **Export HTML Report** | Save a report viewable in a web browser. |
| **Show Receptor Tools** | Show/hide the receptor cleaning and preparation controls. |
| **Simple mode** | Hide some advanced controls to reduce visual clutter. It does not reset their saved values. |
| **Night Mode** | Switch the interface theme. |
| **RUN DOCKING** | Validate inputs, review settings and start the docking jobs. |

The main window scrolls. On smaller screens, scroll to reach controls; the **RUN DOCKING** button is placed in the footer.

### Important sections

**Receptor Tools:** Download/clean PDBs, prepare receptor PDBQT files, install dependencies and read setup information.

**Receptor table:** A list of receptor `.pdbqt` files with a docking mode, selected residues, padding and status.

**Docking configuration:** A single-ligand field, Vina executable, box padding, repeats, exhaustiveness, advanced Vina options, performance settings, output options and PLIP controls.

**Ligand Preparation:** Converts chemical structures or SMILES into prepared ligand PDBQT files.

**Ligand Queue:** A batch list of prepared ligand PDBQT files. **When the queue is nonempty, it takes precedence over the single Ligand field.**

**Experiment Notes:** Optional free text copied into the saved configuration records.

**Live Vina / PLIP Commands:** Shows live command output. Use **Copy**, **Clear** and **Auto-scroll** as needed. Clearing this display is not the same as deleting saved project logs.

If an advanced control seems to have disappeared, **untick Simple mode**.

## 5. Downloading and cleaning receptor structures

Click **1. Clean / Download PDBs** under **Receptor Tools**.

The separate receptor-cleaner window has **Panel & Build**, **Integration** and **Notes** tabs.

### 5.1 Create a receptor panel

In **Panel & Build**:

1. Give the panel a useful **Panel name**.
2. Click **New** if you want an empty panel. The cleaner may open with a bundled example panel already loaded; remove entries you do not intend to process.
3. Click **Add** and fill in the receptor entry:
   - **PDB ID:** the four-character Protein Data Bank ID.
   - **Target name:** a descriptive protein name.
   - **State / conformation:** e.g. the source structure's known state, when available.
   - **UniProt accession(s):** **required**; these tell the cleaner which mapped residues belong to the target.
   - **Keep ions:** optional comma-separated ions, such as `NA,CL`.
   - **Note:** optional context.
   - **System type:** Auto-detect, GPCR, non-GPCR membrane/membrane-associated, or soluble protein.
4. Use **Edit**, **Duplicate** or **Remove** to manage entries. Double-click an entry to edit it.
5. Use **Save JSON** or **Export CSV** to save the panel. **Load JSON/CSV** opens an existing panel. **Load DTP-1 panel** loads the included example panel.

For the UniProt and ion fields, entries can be comma- or semicolon-separated.

### 5.2 Build the cleaned panel

1. Choose the **Output folder**.
2. Set the **Ion cutoff (Å)** if you are requesting retained nearby ions.
3. Enable **Force fresh downloads** only when you need to retrieve a fresh copy rather than reuse downloaded data.
4. Enable **VERY detailed debug mode** when you need extensive troubleshooting records.
5. Click **Build cleaned panel** and watch the **Build log**.
6. After completion, click **Open output folder**. Review `manifest.csv` and inspect the actual cleaned structures.

The cleaner uses downloaded structure coordinates and PDBe/SIFTS UniProt mapping to retain the requested target. It is designed to remove unrelated chains, fusion inserts, waters, native ligands and other non-target material. It can also generate optional nearby-ion variants and writes extracted hetero components for review.

Typical cleaned-panel output includes:

```text
cleaned_receptor_panel\
    panel_definition.json
    manifest.csv
    cleaned_protein_only\
    cleaned_with_na_cl\       (where requested/produced)
    hetero_components\
    raw\
    mapping\
    debug\                 (if detailed debugging was enabled)
    FAILURES.txt           (if failures occurred)
```

**The cleaner does not make a receptor ready for Vina.** It deliberately does not assign protonation, charges or docking atom types, repair missing side chains/loops, revert mutations or minimise the receptor. Review the binding pocket and proceed to the receptor PDBQT preparer.

**Integration tab:** The optional VLiP command field is a copyable handoff template. The cleaner **does not run this command automatically**. The normal graphical workflow is to clean, then use the PDBQT preparer in section 6.

## 6. Converting receptor PDB files to PDBQT

Click **2. PDB → docking PDBQT**.

This is the bulk **rigid-receptor** preparer. It calls PDB2PQR/PROPKA for hydrogens and pH-dependent preparation, then Meeko for Vina-compatible receptor output.

### 6.1 Step by step

1. Set the **Input folder** to the directory containing cleaned `.pdb` files, or to the cleaned-panel root.
2. Set a separate **Output folder** for prepared receptor files.
3. Choose the target **pH** and **PDB2PQR force field** (`AMBER`, `CHARMM` or `PARSE`).
4. Choose **Parallel jobs** and a **Stage timeout (s)**.
5. Set options appropriately:
   - **Search subfolders:** find PDB files recursively.
   - **Use cleaned_protein_only when present:** prefer that folder from VLiP's cleaner output.
   - **Overwrite existing PDBQT:** redo outputs already present.
   - **Keep PQR/protonated intermediates:** preserve the intermediate preparation files for inspection.
   - **Remove only irreparable partial residues:** allow limited handling of problematic incomplete residues.
   - **Strip HETATM (metals/cofactors need manual prep):** removes hetero atoms; be careful if the protein needs a bound metal, cofactor or structural ion.
6. Click **Check setup** to verify the preparation dependencies.
7. Click **Scan PDBs** and review the detected input list.
8. Click **Start preparation** and watch each file's **Status** and **Detail** plus the **Run log**.
9. If needed, click **Cancel** to stop the batch.
10. When successful, click **Send successful to VLiP queue**, or keep **Automatically send successful PDBQTs to VLiP queue when preparation finishes** ticked.

The generated PDBQT files are imported into the main VLiP receptor queue through an internal handoff. Missing, invalid and duplicate paths are not silently added. You can also import the PDBQT files with **Add Files...** in the main receptor table.

Typical preparer outputs include `.pdbqt` files, per-file logs, metadata, `manifest.csv`, `run_summary.json`, `BULK_RECEPTOR_PREP.log` and `FAILURES.txt`. Files are saved under the chosen preparer output root; intermediate files may be removed when the corresponding retention option is off.

**Important:** A prepared receptor should still be inspected. The preparer cannot guarantee that protonation, missing chemistry, metal coordination or unusual residues have been treated correctly.

## 7. Preparing ligands from SMILES or structure files

Click **SMILES / SDF → docking PDBQT** under **Ligand Preparation**.

### 7.1 Add ligand sources

You can either:

- Click **Add files** for `.sdf`, `.sd`, `.mol`, `.mol2`, `.smi`, `.smiles`, `.csv` or `.txt` sources; or
- Type/paste SMILES in the text area, **one molecule per line**, optionally followed by a name.

Example:

```text
CCO ethanol
CC(=O)O acetic_acid
```

Use **Remove selected** and **Clear** to manage the input files. Choose an **Output** folder before preparation.

### 7.2 Understand preparation choices

| Option | What it does |
| --- | --- |
| **Target pH** | Sets the target for the optional rule-based pH adjustment. Initial value is `7.4`. |
| **Ionisation → Adjust for pH (Open Babel model)** | Attempts pH-dependent charge adjustment. This is a prediction, not an experimental pKa determination. |
| **Ionisation → Preserve source charge state** | Keeps the source charge specification instead of applying the pH adjustment model. |
| **Keep largest organic fragment** | Removes other disconnected components such as many counterions/salts. Use care with multicomponent systems. |
| **Save prepared 3D SDF files** | Saves prepared ligand structures as `.sdf` alongside docking files. |
| **Enumerate tautomers** | Generates alternative tautomeric states, up to the selected maximum. |
| **Enumerate unspecified stereochemistry** | Generates possible stereochemical alternatives where the input does not specify them. |
| **Maximum total states per input** | Limits the combined number of states produced per input compound. |
| **3D conformers per state** | Controls the conformational search used during preparation. |
| **Reproducible seed** | Fixes the ligand-preparation random seed for repeatability. |
| **Replace matching outputs...** | Allows replacing files made using matching preparation settings. |
| **Add successful prepared states to the main VLiP ligand queue** | Automatically hands successful `.pdbqt` outputs back to the main docking window. |

The source's initial values include **4 tautomers maximum, 8 stereoisomers maximum, 16 total states maximum, 20 conformers per state**, and seed **202641**. These are configuration defaults, not proof that every state is chemically realistic.

### 7.3 Prepare and review

1. Click **Check tools** to test the ligand-preparation environment.
2. Click **PREPARE LIGANDS**.
3. Read the **Results** table, which reports status, source, state, charge, torsions and output PDBQT file.
4. Click **Open output** to inspect the files and audit records.
5. Review the prepared SMILES, stereochemistry, charges and warnings before treating the outputs as scientifically useful.

The output folder includes:

```text
ligand_output\
    prepared_pdbqt\
    prepared_sdf\                 (if enabled)
    audits\
    VLiP_LIGAND_PREPARATION_MANIFEST.json
    VLiP_LIGAND_PREPARATION_MANIFEST.csv
```

The ligand preparer may create **multiple prepared PDBQT files from one source molecule** because tautomer and stereochemical states can be enumerated. If handoff is enabled, the successful prepared states are added to the docking ligand queue.

**A charge, tautomer, stereoisomer or conformer chosen by software is not automatically the experimentally dominant state.** The JSON audit files record preparation details to support checking and reproducibility.

## 8. Managing receptor and ligand queues

### Receptor queue

- **Add Files...:** add one or more pre-existing receptor `.pdbqt` files.
- **Remove:** remove selected receptor rows from the queue; this does not delete the source file.
- **Move Up / Move Down:** alter receptor processing order.
- **Undo:** undo the most recent supported queue change.
- **Double-click a receptor:** edit `Whole`/`Active` mode, residues and padding.
- **Right-click a receptor:** show context actions.
- **Drag a row within the table:** reorder entries.

### Ligand queue

- **Add current ligand:** add the PDBQT shown in the single **Ligand** field to the queue.
- **Add Files...:** add prepared ligand `.pdbqt` files directly.
- **Remove / Move Up / Move Down / Clear Queue / Undo:** manage processing order and contents.
- **Right-click a ligand:** show context actions.
- **Drag a row within the table:** reorder entries.

**File drag-and-drop from Windows Explorer is deliberately disabled.** Use **Add Files...**. Dragging *rows inside a VLiP table* is supported.

**Queue priority rule:** if the ligand queue contains anything, **RUN DOCKING uses that queue and ignores the single Ligand field**. If the queue is empty, VLiP uses the single Ligand field. This matters when you think you changed the input but an old queue is still loaded.

The program checks `.pdbqt` formatting and rejects invalid/missing files. Duplicate queue paths are ignored by the preparation handoffs.

## 9. Choosing a docking region

Double-click the desired receptor row in the main receptor table.

### 9.1 Whole mode

**Whole** creates a rectangular docking box from the minimum and maximum coordinates of **all parsed receptor atoms**, plus the selected padding in each dimension. It does **not** mean that the receptor is flexible or that every point on its surface is equally sampled.

Large proteins can produce very large search boxes. Check the preview and interpret the consequences for search coverage and runtime.

### 9.2 Active mode

**Active** creates the rectangular box around specifically selected receptor residues. Enter comma-separated residue IDs such as:

```text
42
A:42
A:42B
A:42,A:45,A:78
```

Here `A` is a chain ID, `42` a residue number and `B` an insertion code in `A:42B`. A bare number such as `42` is permitted only if it matches an unambiguous residue. A blank-chain residue can be written with `_:`. Residue numbers and chains must match the **prepared receptor PDBQT**, not just an unrelated reference sequence.

VLiP checks that the specified residues exist and that an unqualified residue number is not ambiguous across chains/insertion codes. **If Active selection is invalid, VLiP reports an error; it will not silently change the experiment to Whole mode.**

### 9.3 Padding

**Default Padding** starts at `10` Å. Each receptor row can override it. The implementation adds the padding value to each calculated box **dimension**:

```text
box size in an axis = (maximum selected atom coordinate
                       − minimum selected atom coordinate) + padding
```

Thus, padding is the **total extra size per dimension**, not a promise of that much empty space on each side. Box centres are derived from the selected atoms' coordinate ranges.

### 9.4 Interactive 3D Preview

Select a receptor and click **Interactive 3D Preview**. This shows the calculated box and a molecular view, with tools for nearby residues, surface inspection and contacts.

If a ligand is selected or queued, VLiP may place a copy of its structure at the box centre for visual inspection. **That centred ligand is not a docked pose** and does not modify the original ligand coordinates.

Use Preview to confirm your chosen residues, box location and box dimensions before starting expensive runs.

## 10. Configuring docking

### 10.1 The ordinary settings

| Setting | Meaning |
| --- | --- |
| **Vina** | Path to the AutoDock Vina executable. Usually filled after successful installation. Browse if using an existing executable. |
| **Default Padding** | Additional box size in ångströms; can be overridden for each receptor. |
| **Repeats** | Number of docking searches for each ligand–receptor pairing. Must be a positive integer. |
| **Exhaustiveness** | Vina search effort. Must be a positive integer. More effort generally requires more compute time; it does not guarantee better validity. |
| **Max output poses** | Optional maximum number of poses/modes to report. Blank uses the selected Vina executable's default. |
| **Run PLIP interaction analysis** | Run interaction analysis on generated poses. |
| **Parallel PLIP poses** | Maximum parallel pose-analysis workers, from 1 to 32. `1` is sequential; the interface suggests trying `2` initially. |
| **Experiment Notes** | Explanatory text copied into the saved run configuration. |

### 10.2 Advanced Vina Options

Click **Advanced Vina Options...** (turn off Simple mode if it is hidden). Available overrides are:

- Maximum output poses/modes (`num_modes`)
- Energy range in kcal/mol (`energy_range`)
- Minimum pose RMSD in ångströms (`min_rmsd`)
- Maximum evaluations (`max_evals`)
- CPU threads (`cpu`)
- Random seed (`seed`)
- Grid spacing in ångströms (`spacing`)
- Disable explicit-atom refinement (`no_refine`)
- Force even grid voxel counts (`force_even_voxels`)

**Blank fields use the selected Vina executable's defaults.** The dialog probes that executable to see which switches it supports; unsupported switches cannot be applied. **Use executable defaults** clears the overrides.

A **fixed, nonzero random seed** can make an identical input/configuration reproducible; it does not mean different runs have become independent samples. With no override, Vina controls its seed according to its own defaults. The maximum pose count is only an upper bound; other filters can return fewer poses.

VLiP's standard workflow does not expose flexible-receptor, scoring-only, local-only, randomisation-only or custom-map docking modes.

### 10.3 Output retention options

- **Merge receptor+ligand (merged.pdbqt):** save combined receptor–ligand `.pdbqt` complexes for poses.
- **Convert to PDB:** save complex `.pdb` structures.
- **Save per-run summary (.txt):** retain additional per-run docking text/output.
- **Run PLIP interaction analysis:** produce PLIP interaction outputs.

**PLIP does not require you to tick Merge or Convert to PDB.** The program creates temporary complex files when necessary and retains only the formats you've selected for permanent output.

### 10.4 Performance controls

The **Docking performance** section offers **Gentle**, **Balanced** and **Full** modes. The source associates these with approximately **25%, 50% and 100% of detected CPU cores**, respectively, using process affinity on supported Windows systems. This is a CPU resource preference, not a guarantee of any particular wall-clock speed.

Enable **Daily schedule** to switch into Gentle mode between the selected **Gentle from** and **until** 24-hour times. Click **Apply schedule** after editing the times. You can also change speed and schedule while a docking run is active from the progress window. For continuous compute-intensive jobs, test how these controls behave on your machine.

## 11. Running, pausing, stopping and resuming

### 11.1 Start a run

1. Select an output folder and check the receptor and ligand queues.
2. Check `Whole`/`Active`, residue IDs, padding, repeats and exhaustiveness.
3. Review the PLIP and output options.
4. Click **RUN DOCKING**.
5. The **Check Before Docking** window lists input paths, number of jobs, options, versions, expected output files, any estimate from earlier jobs, and warnings.
6. Use **Copy Configuration** or **Export Configuration…** if you want a copy before the run.
7. Choose **Go Back** to correct settings or **CONFIRM AND RUN** to begin.

Use a **new empty project folder** for an unrelated new experiment. VLiP warns if an output folder contains files, and a new run can replace matching generated summaries.

### 11.2 During a run

The progress window reports overall job progress, current ligand/receptor, repeat, status and an estimated time where available.

| Button | Behaviour |
| --- | --- |
| **Pause after step** | Requests a safe pause **after the currently running Vina/PLIP subprocess finishes**. It does not freeze a Vina search mid-command. |
| **Resume** | Continues a paused run. |
| **Stop After Receptor** | Finishes the current receptor's repeats and then ends the run cleanly. |
| **Cancel Run** | Requests cancellation and attempts to terminate an active subprocess. Partial output may remain. |

You can switch **Gentle / Balanced / Full** and change the daily schedule in this window.

### 11.3 Resume an interrupted run

VLiP saves checkpoint data globally beside its executable/source and in the project folder. At startup, it can offer to restore an unfinished project's settings. When you click **RUN DOCKING** with an unfinished **matching configuration**, it can offer to continue at the next saved job index.

For reliable resuming:

1. Keep the project output folder and its checkpoint files.
2. Keep the **same input files at the same paths**.
3. Restore the previous setup when prompted.
4. Do **not** change receptor/ligand selection, order or the run settings that form part of the checkpoint match.
5. Click **RUN DOCKING**, accept **Continue previous run?**, and review the pre-run summary before confirming.

If the current configuration does not match the saved one, VLiP warns and starts from the beginning if you proceed. Resuming skips previously checkpointed jobs; it is **not** a guarantee that a partly finished Vina subprocess can resume its internal search. A job interrupted mid-execution can be repeated.

**Avoid unplugging a USB drive while VLiP is using it.** The checkpoint logic can make interrupted work recoverable, but it cannot repair missing files, corrupt write operations or an unavailable output drive.

### 11.4 Job states

- **RUNNING:** job currently executing.
- **COMPLETE:** Vina and the requested post-processing finished.
- **PARTIAL:** docking finished but one or more requested PLIP pose analyses failed.
- **FAILED:** the Vina job or post-processing failed.
- **SKIPPED:** the job could not be started because a receptor/context prerequisite failed.

A batch can reach its final job and still report **Completed with issues**. Check the per-job status and logs; do not interpret a completed progress bar as proof that every result succeeded.

## 12. Where the results are saved

The following is a simplified layout of an ordinary project, showing common files and folders. Exact contents depend on which output and PLIP options were enabled.

```text
My_VLiP_Project\
│
├── all ligands docking scores.txt       # combined docking-score report
├── all ligands plip.txt                 # combined PLIP report, when enabled
├── VLiP_COMPLETE_SETTINGS_USED.txt      # full saved run configuration
├── VLiP_Project_Report.html             # browser-readable project report
├── VLIP_RUN.html / VLIP_RUN.json        # portable folder markers (when written)
├── vlip_project.json                    # project checkpoint/state
├── VLiP_PERFORMANCE_HISTORY.txt         # speed/schedule changes, when recorded
├── receptor_reports\                    # grouped receptor PLIP summaries
├── logs\
│   └── vlip_run.log                     # project log
│
└── <ligand_name>\
    ├── runlog.txt
    ├── all_runs_summary.txt
    ├── <receptor_name>\
    │   ├── summary\                     # run summaries and error logs
    │   └── run_1\
    │       ├── dock\
    │       │   └── dock.pdbqt             # multi-pose Vina output
    │       ├── poses\
    │       │   ├── pose1.pdbqt
    │       │   └── pose2.pdbqt            # additional poses if returned
    │       └── merged\                   # saved merged poses if enabled
    │
    ├── pdb\
    │   └── <receptor_name>\run_1\       # exported complex PDBs if enabled
    └── plip\
        └── <receptor_name>\run_1\       # per-pose PLIP outputs if enabled
```

Actual filenames also include per-job settings records (`VLiP_SETTINGS_USED.txt`) and pose-level PLIP summaries where appropriate. The software uses distinct output stems when needed to avoid collisions from files with identical base names.

### Which output should I open?

- **Quick docking comparison:** `all ligands docking scores.txt`, or the **Open Results** interface.
- **Every pose from one Vina job:** `<ligand>/<receptor>/run_N/dock/dock.pdbqt`.
- **One pose:** `<ligand>/<receptor>/run_N/poses/poseN.pdbqt`.
- **Interaction details:** `all ligands plip.txt`, per-receptor/per-pose PLIP summaries or the matched PLIP panel in the 3D viewer.
- **Exactly what settings were used:** `VLiP_COMPLETE_SETTINGS_USED.txt` and the individual `VLiP_SETTINGS_USED.txt` files.
- **Errors:** `<ligand>/runlog.txt`, `logs/vlip_run.log`, error files under `summary`, and the command audit directory (its location may differ between source and packaged builds).
- **Report to share:** `VLiP_Project_Report.html`.

## 13. Reading docking scores and PLIP interactions

### 13.1 Docking scores

AutoDock Vina reports an estimated **affinity score in kcal/mol**. In Vina's scoring convention, **more negative** values are scored more favourably. However:

- A more negative docking score is **not** a measured binding affinity or a potency measurement.
- Score differences can reflect box choice, protonation, receptor preparation, conformational sampling and the scoring function.
- Scores from different receptors or different methodological setups should not be treated as directly interchangeable experimental quantities.
- Inspect the actual pose geometry and whether chemically plausible interactions are present.

### 13.2 PLIP analysis

PLIP identifies and summarises molecular interactions from a supplied protein–ligand complex. VLiP can run it for individual docking poses and collect the summaries. PLIP can describe interaction categories such as hydrogen bonds, hydrophobic contacts, salt bridges, aromatic interactions and other supported classes.

**An interaction classification is not a biochemical validation.** In particular, inspect the actual atom types, protonation/charge state, distances, receptor identity and pose before accepting a reported salt bridge or hydrogen bond as chemically meaningful.

### 13.3 Open Results

Click **Open Results**, then select a project folder. The results explorer shows:

- Ligand, receptor and run number.
- Affinity score (kcal/mol).
- Job status and PLIP status.
- A text **Filter**.
- Clickable column headings for sorting.

Choose a row and use **View 3D Pose**, **Open Output Folder** or **Open PLIP Report**. Double-clicking a result opens the 3D viewer. **Compare Project** and **Export HTML** are also available from this window.

## 14. Using the built-in 3D viewer and PyMOL

VLiP has an interactive molecular viewer for both pre-docking **Interactive 3D Preview** and post-docking **View 3D Pose**.

### Mouse and keyboard controls

| Action | Control |
| --- | --- |
| Rotate | Left-click and drag. |
| Pan | Shift + drag, or middle-button drag. |
| Zoom | Mouse wheel. |
| Inspect atom | Click it. |
| Atom actions | Right-click in the molecular view. |
| Measure distance | Click **Measure**, or press **M**, then select two atoms. |
| Fit active region/ligand | **F**. |
| Fit full receptor or nearby scene | **A** (depends on Preview versus Pose Viewer). |
| Reset orientation | **R** or **Reset view**. |
| Clear selection | **Escape**. |

### Viewer panels and controls

- Select a returned docking pose/mode from the pose selector.
- Where available, change between docking results using the result selector.
- Use the **Display** tab to control nearby residues, residue labels, hydrogens, ligand atom labels, contact guides, surface effects, pocket radius/opacity and viewing depth.
- Use **Inspect** to examine selected atoms, nearby contacts and measured distances. Buttons include **Copy details**, **Centre atom**, **Highlight residue** and **Clear measurements**.
- Read the matched **PLIP** summary for the **currently selected pose**. The viewer is designed not to substitute another pose's PLIP report.
- Use **Open full PLIP report** for further information, if a report exists.
- Use **Export SVG snapshot** to save a scalable image of the current molecular view.
- Use **Help** in the viewer to see its built-in control instructions.

**Contact guides drawn from proximity and atom types are visual aids, not automatically confirmed interactions.** The viewer's built-in geometry rendering does not replace careful molecular analysis. The Pose Viewer concentrates on the ligand and nearby receptor region, rather than drawing the full receptor in every result view.

### PyMOL

Click **View in PyMOL** from the pose viewer if PyMOL is installed and discoverable. This is optional. If PyMOL is unavailable, use the bundled 3D viewer or install PyMOL through its official website.

At the end of a successful or partially successful docking batch, VLiP may automatically open a pose viewer for the produced results.

## 15. Recent projects, comparison and HTML reports

### Recent Projects

Click **Recent Projects** to see saved projects and their paths, statuses, progress, last update and notes. Available actions include:

- **Open Results**: explore an earlier run.
- **Compare**: compare it with another project.
- **Export HTML**: produce a browser report.
- **Use as Output**: select that folder as the current output location and restore its saved notes.
- **Remove from List**: remove the shortcut from the recent-project list; this does not mean project files were deleted.

### Compare Projects

Choose two **different** VLiP project folders. The comparison window contains:

- **Settings and Software:** side-by-side configuration values, marked as same or different.
- **Docking Scores:** matching ligand/receptor/run rows, affinities for Project A and B, and the numerical difference `B − A`. Missing values are marked.

A score difference is not necessarily evidence of a chemical difference. First check whether the settings, source structures and program versions match.

### Export HTML Report

Click **Export HTML Report**, select the project and choose where to save the `.html` file. The report can be opened in a browser and shared as a project overview. It does not substitute for preserving the original input files and detailed audit records.

## 16. Logs, audit trails and reproducibility

VLiP's source implements several layers of record-keeping:

1. **Complete settings record:** `VLiP_COMPLETE_SETTINGS_USED.txt` in each docking project. Includes software/version information, input details, selected box settings, options and experiment notes.
2. **Per-job settings:** `VLiP_SETTINGS_USED.txt`, with exact parameters and Vina commands for relevant jobs.
3. **Checkpoint/state:** `vlip_project.json` in the project and `vlip_docking_progress.json` beside the program for restoring matching interrupted work.
4. **Run logs:** `logs/vlip_run.log`, ligand `runlog.txt`, and stage-specific errors.
5. **Command audit:** a timestamped folder under `VLiP_Command_Audit` relative to the running source/extraction directory, or a configured/fallback location. **The path can differ in packaged one-file executables.** It contains a combined command log and stage files for environment setup, PDB download, receptor cleaning, receptor preparation, ligand preparation, Vina docking, PLIP, and related commands.
6. **Preparation manifests:** receptor/ligand preparation output records including statuses, hashes, settings and warnings.
7. **Performance history:** saved speed/schedule changes when recorded.

To keep a scientifically reproducible project, retain:

- The original receptor structure and UniProt mapping choices.
- The cleaned receptor and prepared receptor `.pdbqt` used for docking.
- The exact prepared ligand `.pdbqt` and preparation manifest.
- The project results, settings, checkpoint and logs.
- The Vina and PLIP versions, random seeds (when known) and method details.
- Human notes documenting any manual corrections or exceptions.

**The presence of an audit trail does not, by itself, validate the methodology.** It makes it possible to investigate what happened.

## 17. Troubleshooting

| Problem | What to check |
| --- | --- |
| **Vina not found / setup incomplete** | Use **Install / Repair ALL**, then **Diagnose**. Check whether the Vina executable path points to a real file. |
| **Ligand or receptor preparer does not open** | Verify the managed scientific runtime in **Diagnose**, then rerun installation/repair. |
| **Missing PDB / UniProt mapping** | Confirm the four-character PDB ID and correct target UniProt accession(s). Consult the cleaner's `manifest.csv`, `FAILURES.txt` and debug files. |
| **No PDB files found by preparer** | Check **Input folder**, **Search subfolders** and the **Use cleaned_protein_only when present** option. |
| **Prepared file reported invalid** | Check the detailed preparation log and the PDBQT itself. Do not simply rename a PDB file to `.pdbqt`. |
| **Active residues do not match** | Check PDBQT chain IDs, residue numbers and insertion codes. Use `A:42` instead of `42` when ambiguous. |
| **Unexpected ligand was docked** | Clear the **Ligand Queue**; a nonempty queue overrides the single Ligand field. |
| **PLIP missing or partially failed** | Check whether PLIP was enabled, inspect `plip` output and run logs, and review the prepared complex. A successful Vina job can still have partial PLIP results. |
| **The docking job takes too long** | Examine the number of jobs, box volume, exhaustiveness, repeats, output pose count and active performance mode. |
| **Cannot resume** | Restore the original output folder, files, order and settings. Check `vlip_project.json` and whether the incomplete checkpoint matches the current configuration. |
| **Unexpected restart/overwritten summaries** | Use a new empty output folder for unrelated experiments; the program may replace matching generated outputs in a fresh run. |
| **Output drive unplugged / write errors** | Reconnect the same drive and check integrity. Review checkpoint warnings in `logs/vlip_run.log`. Resume may be limited if files or checkpoints are missing. |
| **3D pose viewer appears blank** | Check whether docking produced readable `dock.pdbqt`/individual pose files and whether the correct result was selected. |
| **PyMOL button cannot launch it** | PyMOL is optional and must be installed separately. Use the built-in viewer in the meantime. |
| **Cannot find advanced options** | Turn off **Simple mode**. |
| **Windows paths are too long** | Use a short project path such as `D:\VLiP\Project01`, and check path-length warnings in the log. |
| **Program seems unresponsive during a large job** | Look at the live command pane and progress window. **Pause after step** waits for the active external subprocess rather than interrupting it mid-search. |

When reporting a reproducible bug, include the VLiP version, Windows version, the exact steps, relevant input types, `vlip_diagnostics.txt`, the setup log if relevant, and a redacted copy of the job/settings/error records. You should remove any sensitive local paths or private information before making logs public.

## 18. Scientific limitations and good practice

- **Binding prediction is not functional evidence.** Docking cannot establish agonism, antagonism, allostery, pharmacological potency, selectivity or clinical effects.
- **Preparation determines the model.** Protonation, tautomer selection, stereochemistry, missing residues and retained ions can substantially affect results.
- **Rigid receptors are an approximation.** This release's receptor preparation/docking workflow is not a molecular-dynamics simulation and does not represent full conformational flexibility.
- **Search boxes matter.** A ligand can only be assessed within the configured search space; a large Whole box and a focused Active box are different experiments.
- **PLIP is descriptive.** Review reported interactions against actual atom types and geometry; automated classifications can be wrong when input chemistry is wrong.
- **Repeat runs have to be documented.** A fixed random seed improves exact repeatability but does not create independent sampling. Changing seeds or protocols changes what the runs test.
- **Validation is separate work.** For scientific use, compare against appropriate reference structures, controls and independent evidence using a method suited to your research question.

VLiP is a workflow tool. Its convenience and reproducibility features are useful, but they do not turn computational predictions into experimentally established results.

## 19. Frequently asked questions

**Do I have to prepare everything in VLiP?**  
No. If you already have correctly prepared receptor and ligand `.pdbqt` files, you can add them directly and dock. The preparers are there to make input creation more accessible and repeatable.

**Can I dock multiple ligands against multiple receptors?**  
Yes. Load multiple receptors and add multiple ligands to the queue. VLiP runs the combinations, including your specified number of repeats.

**Can I use the program without PLIP?**  
Yes. Untick **Run PLIP interaction analysis** to perform docking without PLIP post-analysis.

**Does the program have to keep the merged PDBQT files for PLIP?**  
No. Temporary complex files are produced when PLIP needs them, regardless of whether you choose to retain merged PDBQT/PDB exports.

**Why are there several ligand PDBQT files for one SMILES?**  
The ligand preparer can enumerate alternative tautomeric and unspecified stereochemical states. Each accepted state can have its own prepared output.

**Is the built-in preview a docking result?**  
Not before docking. In **Interactive 3D Preview**, a ligand can be centred within the calculated box solely to help inspect the region.

**Can I stop and continue later?**  
Yes, when a valid unfinished checkpoint exists and the run configuration still matches. The software resumes from saved job boundaries, not the middle of Vina's internal calculations.

**Does VLiP 2.0 run molecular dynamics?**  
No. This is the docking/PLIP-focused version; MD code is kept separately for later development.

**Is PyMOL required?**  
No. VLiP has its own 3D viewer. PyMOL is an optional external viewer.

**Where should I begin if something fails?**  
Run **Diagnose**, then check `logs/vlip_run.log`, the affected ligand's `runlog.txt`, per-job error logs and the command audit folder.

---

**VLiP 2.0 User Guide**  
Guide basis: the supplied `VLiP_2.0(3).py` source and its embedded receptor-cleaner, receptor-preparer and ligand-preparer modules.  
Scope: documented program behaviour as implemented in the inspected source, rather than a record of hands-on tests of a particular Windows installation.