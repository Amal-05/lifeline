import Dexie, { type EntityTable } from "dexie";
import { ulid } from "ulid";
import { signEvent, HybridLogicalClock, type EventEnvelope } from "@lifeline/protocol";

export type SOS = { event_id:string; request_id:string; created_at:string; hlc:string; event:EventEnvelope; people_count:number; categories:string[]; special_needs:string[]; text_original:string; latitude:number|null; longitude:number|null; accuracy_m:number|null; location_source:"gps"|"manual"|"last_known"|"unavailable"; photo?:Blob; voice?:Blob; state:"queued"|"received" };
type DeviceKey = { id:number; private_key:Uint8Array; device_id:string };
class LifelineDB extends Dexie {
  outbox!:EntityTable<SOS,"event_id">; keys!:EntityTable<DeviceKey,"id">;
  constructor(){super("lifeline");this.version(1).stores({outbox:"event_id,request_id,created_at,state",keys:"id"});}
}
export const db=new LifelineDB();
async function identity():Promise<DeviceKey>{
  const existing=await db.keys.get(1);if(existing)return existing;
  const private_key=crypto.getRandomValues(new Uint8Array(32));
  const signed=await signEvent({event_id:ulid(),hlc:new Date().toISOString()+"-0000-init",type:"sos.created",request_id:ulid(),payload:{} ,hops:0},private_key);
  const key={id:1,private_key,device_id:signed.device_id};await db.keys.put(key);return key;
}
export async function queueSOS(input:Omit<SOS,"event_id"|"request_id"|"created_at"|"hlc"|"event"|"state">):Promise<SOS>{
  const created_at=new Date().toISOString(),event_id=ulid(),request_id=ulid(),key=await identity();
  const clock=new HybridLogicalClock(key.device_id.slice(0,8),Date.parse(created_at));
  const event=await signEvent({event_id,hlc:clock.tick(Date.parse(created_at)),type:"sos.created",request_id,payload:{people_count:input.people_count,categories:input.categories,special_needs:input.special_needs,text_original:input.text_original,location:{latitude:input.latitude,longitude:input.longitude,accuracy_m:input.accuracy_m,source:input.location_source}},hops:0},key.private_key);
  const record:SOS={...input,event_id,request_id,created_at,hlc:event.hlc,event,state:"queued"};await db.outbox.add(record);return record;
}
export async function queueFollowup(original:SOS,state:"still_needs_help"|"safe"):Promise<SOS>{
  const created_at=new Date().toISOString(),event_id=ulid(),key=await identity();
  const clock=new HybridLogicalClock(key.device_id.slice(0,8),Date.parse(created_at));
  const event=await signEvent({event_id,hlc:clock.tick(Date.parse(created_at)),type:"sos.ping",request_id:original.request_id,payload:{state},hops:0},key.private_key);
  const record:SOS={...original,event_id,created_at,hlc:event.hlc,event,state:"queued"};
  delete (record as Partial<SOS>).photo;delete (record as Partial<SOS>).voice;
  await db.outbox.add(record);return record;
}
export async function syncOutbox(baseUrl:string):Promise<number>{
  if(!navigator.onLine)return 0;const pending=await db.outbox.where("state").equals("queued").toArray();let synced=0;
  for(const item of pending){
    const attachments:Record<string,string>={};
    for(const kind of ["photo","voice"] as const){const blob=item[kind];if(blob){const form=new FormData();form.set("file",blob,`${kind}.bin`);const media=await fetch(`${baseUrl}/media`,{method:"POST",body:form});if(!media.ok)continue;attachments[kind]=(await media.json()).media_id;}}
    const event={...item.event,payload:{...item.event.payload,media_ids:attachments}};
    // Media IDs are added after upload, so re-sign the envelope with the same stable event ID.
    const key=await db.keys.get(1);if(!key)continue;
    const signed=await signEvent({event_id:event.event_id,hlc:event.hlc,type:event.type,request_id:event.request_id,payload:event.payload,hops:event.hops},key.private_key);
    const response=await fetch(`${baseUrl}/sync`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({protocol_version:1,events:[signed],known_event_ids:(await db.outbox.toArray()).filter(x=>x.state==="received").map(x=>x.event_id),highest_hlc_by_device:{}})});
    if(!response.ok)continue;const result=await response.json();
    if(result.accepted_ids.includes(item.event_id)){await db.outbox.update(item.event_id,{state:"received",event:signed});synced++;}
  }
  return synced;
}
