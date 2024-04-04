import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Union

import GSASIIscriptable as G2sc  # TODO (maffettone): Sort out install into env for srv
import numpy as np
from numpy.typing import ArrayLike

logger = logging.getLogger(__name__)


# class RefinementAgent(PDFReporterMixin, PDFBaseAgent):
class RefinementAgent:

    def __init__(
        self,
        *,
        cif_paths: List[Union[str, Path]],
        refinement_params: List[dict],
        inst_param_path: Union[str, Path],
        **kwargs,
    ):
        self._cif_paths = cif_paths
        self._refinement_params = refinement_params
        self._inst_param_path = inst_param_path
        self._recent_x = None
        self._recent_y = None
        self._recent_uid = None
        super().__init__(**kwargs)
        self.report_on_tell = True

    @property
    def cif_paths(self):
        return self._cif_paths

    @cif_paths.setter
    def cif_paths(self, cif_paths):
        self._cif_paths = cif_paths
        self.close_and_restart()

    @property
    def refinement_params(self):
        return self._refinement_params

    @refinement_params.setter
    def refinement_params(self, refinement_params):
        self._refinement_params = refinement_params
        self.close_and_restart()

    @property
    def inst_param_path(self):
        return self._inst_param_path

    @inst_param_path.setter
    def inst_param_path(self, inst_param_path):
        self._inst_param_path = inst_param_path
        self.close_and_restart()

    def unpack_run(self, run):
        self._recent_uid = run.metadata["start"]["uid"]
        return super().unpack_run(run)

    def tell(self, x, y) -> Dict[str, ArrayLike]:
        self._recent_x = x
        self._recent_y = y
        return dict(independent_variable=x, observable=y)

    def _do_refinement(self, cif_path: Path, refinement_params: dict):
        """Run refinement in temproary directory, return residuals, data array, and cell dictionary

        Returns
        -------
        residuals: flort
            RwP

        data: np.array
            data array consist of a of stacked 6 np.arrays containing in order:
            the x-postions (two-theta in degrees),
            the intensity values (Yobs),
            the weights for each Yobs value
            the computed intensity values (Ycalc)
            the background values
            Yobs-Ycalc

        cell: Tuple[dict, dict]
            Dictionaries of unit cell values and uncertainties. Keys are ["length_a", "length_b", "length_c",
            "angle_alpha", "angle_beta", "angle_gamma", "volume"]
        """
        with TemporaryDirectory() as tmp_dir:  # TODO (maffettone): Can this be replaced by buffers?
            # Save the data for gsas
            np.savetxt(
                Path(tmp_dir) / "data.xy",
                np.column_stack([self._recent_x, self._recent_y]),
                delimiter=",",
                fmt="%1.10f",
            )

            # create g2 project file
            gpx = G2sc.G2Project(newgpx=str(Path(tmp_dir) / "project.gpx"))

            # load data
            hist = gpx.add_powder_histogram(
                Path(tmp_dir) / "data.xy", self.inst_param_path
            )  # add 1D data + instr prms

            # add phase
            phasename = Path(cif_path).stem
            phase = gpx.add_phase(cif_path, phasename=phasename, histograms=[hist])

            gpx.set_refinement(refinement_params, histogram="all", phase=phasename)

            gpx.do_refinements([{}])

            return hist.residuals["wR"], hist.data["data"], phase.get_cell_and_esd()

    def report(self) -> Dict[str, ArrayLike]:

        gsas_rwps = []
        gsas_ycalcs = []
        gsas_ydiffs = []
        gsas_as = []
        gsas_bs = []
        gsas_cs = []
        gsas_alphas = []
        gsas_betas = []
        gsas_gammas = []
        gsas_volumes = []

        for cif_path, refinement_params in zip(self.cif_paths, self.refinement_params):
            residual, data, cell = self._do_refinement(cif_path, refinement_params)
            gsas_rwps.append(residual)
            gsas_ycalcs.append(data[:, 3])
            gsas_ydiffs.append(data[:, 5])
            gsas_as.append(cell["length_a"])
            gsas_bs.append(cell["length_b"])
            gsas_cs.append(cell["length_c"])
            gsas_alphas.append(cell["angle_alpha"])
            gsas_betas.append(cell["angle_beta"])
            gsas_gammas.append(cell["angle_gamma"])
            gsas_volumes.append(cell["volume"])

        return dict(
            data_key=self.data_key,
            roi_key=self.roi,
            roi=self.roi,
            norm_region=self.norm_region,
            observable_uid=self._recent_uid,
            independent_variable=self._recent_x,
            observable=self._recent_y,
            cif_paths=self.cif_paths,
            inst_param_path=self.inst_param_path,
            refinement_params=self.refinement_params,
            gsas_rwps=np.array(gsas_rwps),
            gsas_ycalcs=np.stack(gsas_ycalcs),
            gsas_ydiffs=np.stack(gsas_ydiffs),
            gsas_as=np.array(gsas_as),
            gsas_bs=np.array(gsas_bs),
            gsas_cs=np.array(gsas_cs),
            gsas_alphas=np.array(gsas_alphas),
            gsas_betas=np.array(gsas_betas),
            gsas_gammas=np.array(gsas_gammas),
            gsas_volumes=np.array(gsas_volumes),
        )

    def ask(self, batch_size):
        """This is a passive agent, that does not request next experiments. It does analysis."""
        raise NotImplementedError