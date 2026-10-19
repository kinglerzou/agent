/** Incremental UTF-8 SSE decoder; frames can span any number of network chunks. */
export async function consumeStream(
  body: ReadableStream<Uint8Array>,
  onData: (data: string) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const chunk = await reader.read();

      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);

        buffer = buffer.slice(boundary + 2);

        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice('data:'.length).trimStart())
          .join('\n');

        if (data) onData(data);
        boundary = buffer.indexOf('\n\n');
      }
      if (chunk.done) break;
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
