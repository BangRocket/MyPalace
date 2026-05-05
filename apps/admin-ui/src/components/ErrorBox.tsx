import { HttpError } from "../api/client";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  let message = "Unknown error";
  if (error instanceof HttpError) {
    message = error.message;
  } else if (error instanceof Error) {
    message = error.message;
  } else if (typeof error === "string") {
    message = error;
  }
  return (
    <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-red-800 dark:text-red-200 text-sm rounded-md px-4 py-3 my-4">
      {message}
    </div>
  );
}
