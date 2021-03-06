import bisect
from typing import Optional

import numpy as np

from ..data import ChunkedStateDataset
from ..kinematic import Perturbation
from ..rasterization import Rasterizer
from .ego import EgoDataset


class AgentDataset(EgoDataset):
    def __init__(
        self,
        cfg: dict,
        zarr_dataset: ChunkedStateDataset,
        rasterizer: Rasterizer,
        perturbation: Optional[Perturbation] = None,
        agents_mask: Optional[np.ndarray] = None,
    ):
        assert perturbation is None, "AgentDataset does not support perturbation (yet)"

        super(AgentDataset, self).__init__(cfg, zarr_dataset, rasterizer, perturbation)
        if agents_mask is None:  # if not provided try to load it from the zarr
            agents_mask = self.load_agents_mask()
        # store the valid agents indexes
        self.agents_indices = np.nonzero(agents_mask)[0]
        # this will be used to get the frame idx from the agent idx
        self.cumulative_sizes_agents = self.dataset.frames["agent_index_interval"][:, 1]
        self.agents_mask = agents_mask

    def load_agents_mask(self) -> np.ndarray:
        """
        Loads a boolean mask of the agent availability stored into the zarr. Performs some sanity check against cfg.
        Returns: a boolean mask of the same length of the dataset agents

        """
        history_num_frames = self.cfg["model_params"]["history_num_frames"]
        future_num_frames = self.cfg["model_params"]["future_num_frames"]
        agent_prob = self.cfg["raster_params"]["filter_agents_threshold"]

        group_name = f"{history_num_frames}_{future_num_frames}_{agent_prob}"
        try:
            agents_mask = self.dataset.root[f"agents_mask/{group_name}"]
        except KeyError:
            print(
                f"cannot find {group_name} in {self.dataset.path},\n"
                f"your cfg has loaded history_num_frames={history_num_frames}, future_num_frames={future_num_frames} "
                f"and filter_agents_threshold={agent_prob};\n"
                "but those values don't have a match among the agents_mask in the zarr\n"
                "You can generate a mask with these value by calling the select_agents.py script."
            )
            exit(1)

        return agents_mask

    def __len__(self) -> int:
        """
        length of the available and reliable agents (filtered using the mask)
        Returns: the length of the dataset

        """
        return len(self.agents_indices)

    def __getitem__(self, index: int) -> dict:
        """
        Differs from parent by iterating on agents and not AV.
        """
        if index < 0:
            if -index > len(self):
                raise ValueError("absolute value of index should not exceed dataset length")
            index = len(self) + index

        index = self.agents_indices[index]
        track_id = self.dataset.agents[index]["track_id"]
        frame_index = bisect.bisect_right(self.cumulative_sizes_agents, index)
        scene_index = bisect.bisect_right(self.cumulative_sizes, frame_index)

        if scene_index == 0:
            state_index = frame_index
        else:
            state_index = frame_index - self.cumulative_sizes[scene_index - 1]
        return self.get_frame(scene_index, state_index, track_id=track_id)

    def get_scene_dataset(self, scene_index: int) -> "AgentDataset":
        """
        Differs from parent only in the return type.
        Instead of doing everything from scratch, we rely on super call and fix the agents_mask
        """

        new_dataset = super(AgentDataset, self).get_scene_dataset(scene_index).dataset

        # filter agents_bool values
        frame_interval = self.dataset.scenes[scene_index]["frame_index_interval"]
        # ASSUMPTION: all agents_index are consecutive
        start_index = self.dataset.frames[frame_interval[0]]["agent_index_interval"][0]
        end_index = self.dataset.frames[frame_interval[1] - 1]["agent_index_interval"][1]
        agents_mask = self.agents_mask[start_index:end_index].copy()

        return AgentDataset(
            self.cfg, new_dataset, self.rasterizer, self.perturbation, agents_mask  # overwrite the loaded one
        )

    def get_scene_indices(self, scene_idx: int) -> np.ndarray:
        """
        Get indices for the given scene. Here __getitem__ iterate over valid agents indices.
        This means ``__getitem__(0)`` matches the first valid agent in the dataset.
        Args:
            scene_idx (int): index of the scene

        Returns:
            np.ndarray: indices that can be used for indexing with __getitem__
        """
        scenes = self.dataset.scenes
        assert scene_idx < len(scenes), f"scene_idx {scene_idx} is over len {len(scenes)}"
        frame_start = self.dataset.frames[scenes[scene_idx]["frame_index_interval"][0]]
        frame_end = self.dataset.frames[scenes[scene_idx]["frame_index_interval"][1] - 1]

        agents_start_index = frame_start["agent_index_interval"][0]
        agents_end_index = frame_end["agent_index_interval"][1] - 1

        mask_valid_indices = (self.agents_indices >= agents_start_index) * (self.agents_indices <= agents_end_index)
        indices = np.nonzero(mask_valid_indices)[0]
        return indices

    def get_frame_indices(self, frame_idx: int) -> np.ndarray:
        """
        Get indices for the given frame. Here __getitem__ iterate over valid agents indices.
        This means ``__getitem__(0)`` matches the first valid agent in the dataset.
        Args:
            frame_idx (int): index of the scene

        Returns:
            np.ndarray: indices that can be used for indexing with __getitem__
        """
        frames = self.dataset.frames
        assert frame_idx < len(frames), f"frame_idx {frame_idx} is over len {len(frames)}"

        agents_start_index = frames[frame_idx]["agent_index_interval"][0]
        agents_end_index = frames[frame_idx]["agent_index_interval"][1] - 1

        mask_valid_indices = (self.agents_indices >= agents_start_index) * (self.agents_indices <= agents_end_index)
        indices = np.nonzero(mask_valid_indices)[0]
        return indices
