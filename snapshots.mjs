import { randomBytes } from 'node:crypto';

// One JPEG in flight per room; snapshots never change the capture track.
export function requestSnapshot(room, emit, now = Date.now()) {
  const cameras = [...room.peers.values()].filter(p => p.role === 'camera' && p.res).sort((a,b) => a.slot-b.slot);
  if (!cameras.length) return;
  if (room.snapshotDue && now < room.snapshotDue) return;
  const index = (room.snapshotIndex || 0) % cameras.length, peer = cameras[index];
  room.snapshotIndex = index + 1; room.snapshotDue = now + 5000;
  room.snapshotRequest = { peer: peer.id, nonce: randomBytes(12).toString('hex'), expires: now + 5000 };
  emit(peer, 'snapshot-request', { nonce: room.snapshotRequest.nonce });
}
export function acceptSnapshot(room, peer, data, now = Date.now()) {
  const request = room.snapshotRequest;
  if (!request || request.peer !== peer.id || request.nonce !== data.nonce || now > request.expires) return null;
  if (typeof data.image !== 'string' || data.image.length > 48000 || !/^data:image\/jpeg;base64,\/9j\//.test(data.image)) throw Error('Ảnh xem trước không hợp lệ.');
  room.snapshotRequest = null;
  const image = { id: peer.id, slot: peer.slot, image: data.image, receivedAt: now };
  room.snapshots ||= new Map(); room.snapshots.set(peer.slot, image); return image;
}
