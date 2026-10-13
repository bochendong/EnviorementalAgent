"""Molecule design as a task provider: edit molecules, measure them, meet a target profile (RDKit).

Chemists change molecules with named edits (put a fluorine on an aromatic carbon, turn a CH into N,
remove a substituent ...) and compute exact properties. Biologists run assays: the activity against
the target and toxicity, both hidden functions of the structure, measured with noise and expensive.
Only molecules someone has made (the starting ones and the products of edits) can be assayed, so the
two roles depend on each other.

The hidden activity is drawn from the seed: a few structural motifs that help (and one that hurts), a
preferred lipophilicity and a size penalty. It is learnable from assays, like a real structure-activity
relationship, and ``oracle="package.module:function"`` replaces it with any SMILES -> float model.

Tasks climb a ladder (a hit, then a lead, then a candidate with low toxicity); thresholds are calibrated
at reset by a search over the edit space, so every episode is solvable. Your own targets can come from
JSON: {"start": [smiles...], "tasks": [{"id", "text", "deps", "final", "need": {"activity": 7,
"qed": 0.5, "mw": 450, "tox": 0.3, "sim": 0.3, "logp_max": 4}}]} (``mw``, ``tox`` and ``*_max`` are
maxima, the rest minima; ``sim`` is the Tanimoto similarity to the first start molecule;
``activity_gain`` asks for that much more activity than the first start molecule has).
"""

from __future__ import annotations

import importlib
import json
import random

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors
from rdkit.Chem import rdChemReactions, rdFingerprintGenerator

from ..core import OpSpec, Role, Score, Task, TaskProvider

RDLogger.DisableLog("rdApp.*")

GROUPS = {"methyl": "C", "fluoro": "F", "chloro": "Cl", "hydroxyl": "O", "amino": "N", "methoxy": "OC",
          "nitrile": "C#N", "trifluoromethyl": "C(F)(F)F", "carboxyl": "C(=O)O", "amide": "C(=O)N",
          "sulfonamide": "S(=O)(=O)N", "morpholine": "N1CCOCC1", "phenyl": "c1ccccc1", "nitro": "[N+](=O)[O-]",
          "piperazine": "N1CCNCC1", "acetamido": "NC(C)=O"}
TEMPLATES = {f"add_{k}": f"[cH:1]>>[c:1]{v}" for k, v in GROUPS.items()}
TEMPLATES.update({
    "aza": "[cH:1]>>[n:1]",  # an aromatic CH becomes N (benzene -> pyridine)
    "acid_to_amide": "[C:1](=O)[OH]>>[C:1](=O)N",
    "acid_to_ester": "[C:1](=O)[OH]>>[C:1](=O)OC",
    "acetylate_amine": "[NX3H2:1]>>[NH:1]C(C)=O",
    "methylate_hydroxyl": "[OX2H:1][c:2]>>C[O:1][c:2]",
})
RXN = {k: rdChemReactions.ReactionFromSmarts(v) for k, v in TEMPLATES.items()}

MOTIFS = {"pyridine": "n1ccccc1", "amide": "C(=O)[NX3]", "hydroxyl": "[OX2H]", "fluoro": "cF", "chloro": "cCl",
          "sulfonamide": "S(=O)(=O)N", "nitrile": "C#N", "methoxy": "c[OX2][CH3]", "morpholine": "N1CCOCC1",
          "trifluoromethyl": "C(F)(F)F", "carboxylic acid": "C(=O)[OH]", "piperazine": "N1CCNCC1"}
ALERTS = {"nitro": "[N+](=O)[O-]", "aniline": "c[NX3H2]", "polyhalogen": "[F,Cl,Br,I]"}
STARTS = ["c1ccccc1C(=O)O", "Cc1ccccc1", "c1ccc(cc1)c1ccccc1", "O=C(Nc1ccccc1)c1ccccc1", "c1ccc2ccccc2c1",
          "c1ccc(cc1)Oc1ccccc1"]
PAT = {k: Chem.MolFromSmarts(v) for k, v in {**MOTIFS, **ALERTS}.items()}


def mol(smiles: str):
    m = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and len(smiles) < 300 else None
    if m is None:
        raise ValueError(f"not a valid SMILES: {smiles!r}")
    return m


def canon(smiles: str) -> str:
    return Chem.MolToSmiles(mol(smiles))


_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def fp(m):
    return _GEN.GetFingerprint(m)


def props(m) -> dict:
    return {"mw": round(Descriptors.MolWt(m), 1), "logp": round(Crippen.MolLogP(m), 2), "qed": round(QED.qed(m), 3),
            "tpsa": round(rdMolDescriptors.CalcTPSA(m), 1), "hbd": rdMolDescriptors.CalcNumHBD(m),
            "hba": rdMolDescriptors.CalcNumHBA(m), "rotatable": rdMolDescriptors.CalcNumRotatableBonds(m),
            "rings": rdMolDescriptors.CalcNumRings(m), "heavy_atoms": m.GetNumHeavyAtoms()}


def edit_products(smiles: str, action: str) -> list[str]:
    m = mol(smiles)
    out = set()
    if action == "remove":
        for b in m.GetBonds():  # cut a single bond from a ring atom to a substituent; keep the bigger part
            a1, a2 = b.GetBeginAtom(), b.GetEndAtom()
            if b.GetBondType() != Chem.BondType.SINGLE or b.IsInRing() or not (a1.IsInRing() or a2.IsInRing()):
                continue
            rw = Chem.RWMol(m)
            rw.RemoveBond(a1.GetIdx(), a2.GetIdx())
            frags = Chem.GetMolFrags(rw.GetMol(), asMols=True, sanitizeFrags=False)
            big = max(frags, key=lambda f: f.GetNumHeavyAtoms())
            try:
                for a in big.GetAtoms():
                    a.SetNoImplicit(False)
                    a.SetNumExplicitHs(0)
                Chem.SanitizeMol(big)
                out.add(Chem.MolToSmiles(big))
            except Exception:  # noqa: BLE001
                pass
    elif action in RXN:
        for prods in RXN[action].RunReactants((m,)):
            p = prods[0]
            try:
                Chem.SanitizeMol(p)
                s = Chem.MolToSmiles(p)
                if Chem.MolFromSmiles(s) is not None:
                    out.add(Chem.MolToSmiles(Chem.MolFromSmiles(s)))
            except Exception:  # noqa: BLE001
                pass
    else:
        raise ValueError(f"unknown edit {action!r}; edits: {sorted(RXN) + ['remove']}")
    return sorted(out)[:24]


class Biology:
    """The hidden structure-activity and toxicity functions of one episode."""

    def __init__(self, seed: int, oracle: str = ""):
        rng = random.Random(f"sar/{seed}")
        names = sorted(MOTIFS)
        good = rng.sample(names, 4)
        bad = rng.choice([n for n in names if n not in good])
        self.weights = {**{g: round(rng.uniform(0.8, 1.6), 2) for g in good}, bad: -round(rng.uniform(1.0, 1.5), 2)}
        self.logp = round(rng.uniform(1.5, 3.5), 1)
        self.alerts = {"nitro": round(rng.uniform(.3, .5), 2), "aniline": round(rng.uniform(.15, .3), 2)}
        self.oracle = None
        if oracle:
            mod, fn = oracle.split(":")
            self.oracle = getattr(importlib.import_module(mod), fn)

    def activity(self, m) -> float:
        if self.oracle is not None:
            return float(self.oracle(Chem.MolToSmiles(m)))
        a = 4.0 + sum(w for k, w in self.weights.items() if m.HasSubstructMatch(PAT[k]))
        a -= 0.4 * max(0.0, abs(Crippen.MolLogP(m) - self.logp) - 1.0)
        a -= 0.01 * max(0.0, Descriptors.MolWt(m) - 400)
        return round(a, 3)

    def tox(self, m) -> float:
        t = 0.05 + sum(w for k, w in self.alerts.items() if m.HasSubstructMatch(PAT[k]))
        t += 0.15 * (len(m.GetSubstructMatches(PAT["polyhalogen"])) >= 3) + 0.08 * max(0.0, Crippen.MolLogP(m) - 4)
        return round(min(1.0, t), 3)


def meets(need: dict, v: dict) -> list[str]:
    """``mw``, ``tox`` and any ``<name>_max`` are maxima; everything else is a minimum."""
    miss = []
    for k, lim in need.items():
        name, top = (k[:-4], True) if k.endswith("_max") else (k, k in ("mw", "tox"))
        x = v[name]
        if (top and x > lim) or (not top and x < lim):
            miss.append(f"{name} {x} {'>' if top else '<'} {lim}")
    return miss


class MoleculeProvider(TaskProvider):
    name = "molecule"

    def __init__(self, chemists: int = 2, biologists: int = 1, noise: float = 0.3, assay_cost: int = 5,
                 tox_cost: int = 3, free_smiles: bool = False, free_roles: bool = False, target_file: str = "",
                 oracle: str = "", calibrate_depth: int = 5):
        self.chemists, self.biologists, self.noise = chemists, biologists, noise
        self.assay_cost, self.tox_cost, self.free_smiles, self.free = assay_cost, tox_cost, free_smiles, free_roles
        self.target_file, self.oracle, self.depth = target_file, oracle, calibrate_depth

    def reset(self, seed: int = 0) -> dict:
        self.rng = random.Random(f"assay/{seed}")
        self.bio = Biology(seed, self.oracle)
        if self.target_file:
            with open(self.target_file) as f:
                data = json.load(f)
            self.starts = [canon(s) for s in data["start"]]
            self.raw = data["tasks"]
            self.ref = fp(mol(self.starts[0]))
            base = self.values(self.starts[0])["activity"]
            for t in self.raw:  # "activity_gain": the hidden activity depends on the seed, so targets can be relative
                if "activity_gain" in t["need"]:
                    t["need"]["activity"] = round(base + t["need"].pop("activity_gain"), 2)
                    t["text"] += f" (activity >= {t['need']['activity']})"
        else:
            self.starts = [canon(random.Random(f"start/{seed}").choice(STARTS))]
            self.raw = self._ladder()
        self.made = {s: "start" for s in self.starts}
        self.ref = fp(mol(self.starts[0]))
        return {"world": "molecule", "start": self.starts, "edits": sorted(RXN) + ["remove"],
                "measures": ["activity (assay, noisy)", "tox (noisy)", "props (exact)"]}

    def values(self, smiles: str) -> dict:
        m = mol(smiles)
        p = props(m)
        return {"activity": self.bio.activity(m), "tox": self.bio.tox(m), "qed": p["qed"], "mw": p["mw"],
                "logp": p["logp"], "sim": round(DataStructs.TanimotoSimilarity(self.ref, fp(m)), 3)}

    def _ladder(self) -> list[dict]:
        """Search the edit space (beam search on the true values) and set the thresholds below what it found."""
        self.ref = fp(mol(self.starts[0]))
        start_act = self.values(self.starts[0])["activity"]
        beam, seen, best = list(self.starts), set(self.starts), {"act": start_act, "lead": 0.0, "cand": 0.0}
        for _ in range(self.depth):
            pool = []
            for s in beam:
                for act in sorted(RXN):
                    for p in edit_products(s, act)[:4]:
                        if p not in seen:
                            seen.add(p)
                            pool.append((p, self.bio.activity(mol(p))))
            if not pool:
                break
            pool.sort(key=lambda pa: -pa[1])
            best["act"] = max(best["act"], pool[0][1])
            full = [(p, self.values(p)) for p, _ in pool[:12]]  # the expensive values only for the best few
            for p, v in full:
                if v["qed"] >= .5 and v["mw"] <= 450:
                    best["lead"] = max(best["lead"], v["activity"])
                    if v["tox"] <= .3:
                        best["cand"] = max(best["cand"], v["activity"])
            full.sort(key=lambda pv: -(pv[1]["activity"] + 2 * pv[1]["qed"] - 2 * pv[1]["tox"]))
            beam = [p for p, _ in full[:3]]
        hit = round(start_act + 0.6 * (best["act"] - start_act), 1)
        lead = round(min(best["lead"] - .3, hit + .3), 1) if best["lead"] else hit
        cand = round(min(best["cand"] - .3, lead + .3), 1) if best["cand"] else lead
        return [
            {"id": "hit", "text": f"Find a molecule with activity >= {hit}.", "need": {"activity": hit}},
            {"id": "lead", "text": f"Find a lead: activity >= {lead}, QED >= 0.5, MW <= 450.",
             "need": {"activity": lead, "qed": 0.5, "mw": 450}, "deps": ["hit"], "reward": 2},
            {"id": "candidate", "text": f"Find a candidate: activity >= {cand}, QED >= 0.5, MW <= 450, "
                                        "toxicity <= 0.3.",
             "need": {"activity": cand, "qed": 0.5, "mw": 450, "tox": 0.3}, "deps": ["lead"], "reward": 3,
             "final": True},
        ]

    def roles(self) -> list[Role]:
        if self.free:
            return [Role("scientist", "Does chemistry and biology.", None, self.chemists + self.biologists)]
        return [Role("chemist", "Makes molecules (edits) and computes their properties.",
                     ("edit", "props", "similarity", "made"), self.chemists),
                Role("biologist", "Runs assays: activity against the target and toxicity (noisy, expensive).",
                     ("assay", "tox", "props", "made"), self.biologists)]

    def ops(self) -> list[OpSpec]:
        S = {"type": "string"}
        return [
            OpSpec("edit", "Make new molecules from one by a named edit; returns every product (they count as "
                           "made). Edits: " + ", ".join(sorted(RXN) + ["remove"]) + ".",
                   {"smiles": S, "action": S}, ("smiles", "action")),
            OpSpec("props", "Exact properties: MW, logP, QED, TPSA, H-bond donors/acceptors, rings ...",
                   {"smiles": S}, ("smiles",)),
            OpSpec("similarity", "Tanimoto similarity (Morgan fingerprints) of two molecules.",
                   {"a": S, "b": S}, ("a", "b")),
            OpSpec("made", "The molecules made so far (newest last), with who made them.", {}),
            OpSpec("assay", "Measure activity against the target (higher is better; noisy).", {"smiles": S},
                   ("smiles",), cost=self.assay_cost),
            OpSpec("tox", "Measure toxicity (0 safe .. 1 toxic; noisy).", {"smiles": S}, ("smiles",),
                   cost=self.tox_cost),
        ]

    def _made(self, smiles: str) -> str:
        s = canon(smiles)
        if not self.free_smiles and s not in self.made:
            raise ValueError(f"{s} has not been made yet (make it with edit)")
        return s

    def apply(self, agent: str, role: Role, op: str, args: dict) -> dict:
        if op == "edit":
            s = self._made(args["smiles"])
            prods = edit_products(s, args["action"])
            for p in prods:
                self.made.setdefault(p, agent)
            return {"products": prods} if prods else {"error": f"{args['action']} does not apply to {s}"}
        if op == "props":
            return {"smiles": canon(args["smiles"]), **props(mol(args["smiles"]))}
        if op == "similarity":
            return {"similarity": round(DataStructs.TanimotoSimilarity(fp(mol(args["a"])), fp(mol(args["b"]))), 3)}
        if op == "made":
            return {"molecules": [{"smiles": s, "by": b} for s, b in list(self.made.items())[-60:]],
                    "total": len(self.made)}
        if op == "assay":
            s = self._made(args["smiles"])
            return {"smiles": s, "activity": round(self.bio.activity(mol(s)) + self.rng.gauss(0, self.noise), 2)}
        if op == "tox":
            s = self._made(args["smiles"])
            t = self.bio.tox(mol(s)) + self.rng.gauss(0, self.noise / 4)
            return {"smiles": s, "tox": round(min(1, max(0, t)), 2)}
        return {"error": f"unknown op {op}"}

    def tasks(self) -> list[Task]:
        return [Task(t["id"], t["text"], "design", tuple(t.get("deps", ())), t.get("reward", 1.0),
                     {"need": t["need"]}, bool(t.get("final"))) for t in self.raw]

    def artifact_schema(self) -> dict:
        return {"type": "string", "description": "a SMILES string"}

    def verify(self, task: Task, artifact, agent: str) -> Score:
        try:
            s = self._made(str(artifact))
        except ValueError as e:
            return Score(False, 0.0, {"error": str(e)})
        v = self.values(s)
        need = next(t["need"] for t in self.raw if t["id"] == task.id)
        miss = meets(need, v)
        frac = 1 - len(miss) / max(1, len(need))
        # what failed is told in words, not the exact hidden activity
        return Score(not miss, 1.0 if not miss else frac, {"smiles": s, "unmet": [m.split()[0] for m in miss]})

    def summary(self) -> dict:
        return {"made": len(self.made)}
