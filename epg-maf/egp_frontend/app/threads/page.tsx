export default function ThreadsIndexPage() {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h2 className="text-lg font-semibold text-slate-800">
          Select a chat or start a new one
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          Each chat is pinned to a single patient. Use the sidebar to open a
          recent chat, or click <strong>+ New chat</strong> to begin.
        </p>
      </div>
    </div>
  );
}
