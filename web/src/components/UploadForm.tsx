"use client";

import { useRouter } from "next/navigation";
import { useState, type ChangeEvent, type DragEvent } from "react";
import { errorMessage, isUnauthorized, uploadDocument } from "@/lib/api";
import { ContainerIcon, UploadIcon } from "./Icons";

const ALLOWED = [".pdf", ".xlsx", ".eml"];

function hasAllowedExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ALLOWED.some((extension) => lower.endsWith(extension));
}

/**
 * Drop files on the dock, or click it to browse. Each file is sent as soon as it is chosen, one after the
 * other, and the server answers at once (reading happens in the background). The server still makes the
 * final decision about type and size; the check here only saves a trip for the obvious mistakes.
 */
export function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  async function sendAll(files: File[]) {
    if (files.length === 0 || progress) return;
    const failures: string[] = [];
    setProblems([]);
    setProgress({ done: 0, total: files.length });
    for (const [index, file] of files.entries()) {
      if (!hasAllowedExtension(file.name)) {
        failures.push(`${file.name}: only PDF, Excel (.xlsx) and e-mail (.eml) files can be read.`);
      } else {
        try {
          await uploadDocument(file);
        } catch (err) {
          if (isUnauthorized(err)) {
            router.replace("/login");
            return;
          }
          failures.push(`${file.name}: ${errorMessage(err)}`);
        }
      }
      setProgress({ done: index + 1, total: files.length });
    }
    setProgress(null);
    setProblems(failures);
    onUploaded();
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from<File>(event.target.files ?? []);
    event.target.value = ""; // so choosing the same file again still counts as a change
    void sendAll(files);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    void sendAll(Array.from<File>(event.dataTransfer.files));
  }

  const busy = progress !== null;

  return (
    <div className="dock-wrap">
      <label
        className={`dock${dragging ? " dock-active" : ""}${busy ? " dock-busy" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input type="file" className="sr-only" multiple accept=".pdf,.xlsx,.eml" onChange={handleChange} disabled={busy} />
        <span className="dock-icon">{dragging ? <ContainerIcon size={30} /> : <UploadIcon size={30} />}</span>
        <span className="dock-text">
          <strong>{busy ? `Sending ${Math.min(progress.done + 1, progress.total)} of ${progress.total}` : dragging ? "Drop to send" : "Drop quotes and invoices here"}</strong>
          <span className="muted">{busy ? "The server reads each file in the background." : "or click to choose files. PDF, Excel or e-mail, up to 10 MB each."}</span>
        </span>
        {busy && <span className="dock-bar" aria-hidden="true" />}
      </label>
      {problems.length > 0 && (
        <ul className="callout callout-bad dock-problems" role="alert">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
