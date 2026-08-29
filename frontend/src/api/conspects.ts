import { request } from "./projects";

export interface ConspectImageRead {
  id: string;
  file_name: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
}

export interface ConspectRead {
  project_id: string;
  node_id: string;
  content_markdown: string;
  revision: number;
  updated_at: string | null;
  images: ConspectImageRead[];
}

export interface ConspectWriteCommand {
  content_markdown: string;
  expected_revision: number;
  retained_image_ids: string[];
}

export interface ConspectSummaryEntry {
  node_id: string;
  position: number;
  title: string;
  content_markdown: string;
  revision: number;
  updated_at: string;
}

export interface ConspectSummaryRead {
  entries: ConspectSummaryEntry[];
}

const conspectsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/conspects`;

const conspectImagesPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/conspect-images`;

export const getConspect = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ConspectRead> =>
  request(`${conspectsPath(projectId)}/${encodeURIComponent(nodeId)}`, { signal });

export const saveConspect = (
  projectId: string,
  nodeId: string,
  command: ConspectWriteCommand,
): Promise<ConspectRead> => request(`${conspectsPath(projectId)}/${encodeURIComponent(nodeId)}`, {
  method: "PUT",
  body: JSON.stringify(command),
});

export const listConspects = (
  projectId: string,
  signal?: AbortSignal,
): Promise<ConspectSummaryRead> => request(conspectsPath(projectId), { signal });

export const uploadConspectImage = async (
  projectId: string,
  nodeId: string,
  file: File,
): Promise<ConspectImageRead> => {
  const body = new FormData();
  body.append("file", file);
  return request(`${conspectsPath(projectId)}/${encodeURIComponent(nodeId)}/images`, {
    method: "POST",
    body,
  });
};

export const deleteConspectImage = (
  projectId: string,
  imageId: string,
): Promise<void> => request(
  `${conspectImagesPath(projectId)}/${encodeURIComponent(imageId)}`,
  { method: "DELETE" },
);

export const conspectImageUrl = (projectId: string, imageId: string): string =>
  `${conspectImagesPath(projectId)}/${encodeURIComponent(imageId)}/file`;
