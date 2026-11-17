import { z } from "zod";
import { monotonicFactory } from "ulid";
import { sign, verify, getPublicKey, hashes } from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2.js";

export const PROTOCOL_VERSION = 1;
hashes.sha512 = sha512;
const nextUlid = monotonicFactory();
export const EventSchema = z.object({ protocol_version: z.literal(1), event_id: z.string().length(26), device_id: z.string(), hlc: z.string(), type: z.string(), request_id: z.string().length(26), payload: z.record(z.string(), z.unknown()), hops: z.number().int().min(0).max(12), signature: z.string() }).strict();
export type EventEnvelope = z.infer<typeof EventSchema>;
export type SyncBundle = { protocol_version: 1; events: EventEnvelope[]; known_event_ids: string[]; highest_hlc_by_device: Record<string, string> };
export function canonicalJson(value: unknown): Uint8Array {
  const sort = (v: unknown): unknown => {
    if (typeof v === "number" && !Number.isFinite(v)) throw new Error("non-finite number in canonical event");
    return Array.isArray(v) ? v.map(sort) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sort(x)])) : v;
  };
  return new TextEncoder().encode(JSON.stringify(sort(value)));
}
const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
const unb64 = (s: string) => Uint8Array.from(atob(s.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-s.length%4)%4)), c => c.charCodeAt(0));
export async function signEvent(fields: Omit<EventEnvelope,"protocol_version"|"event_id"|"device_id"|"signature"> & {event_id?:string}, privateKey: Uint8Array): Promise<EventEnvelope> {
  const body = {protocol_version:1 as const,event_id:fields.event_id??nextUlid(),device_id:b64(await getPublicKey(privateKey)),...fields};
  return EventSchema.parse({...body,signature:b64(await sign(canonicalJson(body),privateKey))});
}
export async function verifyEvent(event: EventEnvelope): Promise<boolean> {
  const {signature,...body}=event;
  try { return await verify(unb64(signature),canonicalJson(body),unb64(event.device_id)); } catch { return false; }
}
export function mergeEventSets(...sets: EventEnvelope[][]): EventEnvelope[] {
  const map=new Map<string,EventEnvelope>();
  for(const event of sets.flat()){const old=map.get(event.event_id);if(old&&String(canonicalJson(old))!==String(canonicalJson(event)))throw new Error(`conflicting event ID: ${event.event_id}`);map.set(event.event_id,event);}
  return [...map.values()].sort((a,b)=>a.event_id.localeCompare(b.event_id));
}
export function lwwWinner<T>(a:{hlc:string;device_id:string;value:T}|undefined,b:{hlc:string;device_id:string;value:T}) { return !a||`${b.hlc}\0${b.device_id}`>`${a.hlc}\0${a.device_id}`?b:a; }
export class HybridLogicalClock {
  private wall:number; private counter=0;
  constructor(private readonly deviceShortId:string,wallMs=Date.now()){this.wall=wallMs;}
  private value():string{return `${new Date(this.wall).toISOString()}-${String(this.counter).padStart(4,"0")}-${this.deviceShortId}`;}
  tick(now=Date.now()):string{if(now>this.wall){this.wall=now;this.counter=0;}else this.counter++;return this.value();}
  receive(remote:string,now=Date.now()):string{
    const [remoteTime,remoteRest]=remote.split("Z-");
    if(!remoteRest)throw new Error("invalid HLC");
    const remoteWall=Date.parse(`${remoteTime}Z`),remoteCounter=Number(remoteRest.split("-",1)[0]);
    if(!Number.isFinite(remoteWall)||!Number.isFinite(remoteCounter))throw new Error("invalid HLC");
    const oldWall=this.wall,oldCounter=this.counter,next=Math.max(now,oldWall,remoteWall);
    this.counter=next===oldWall&&next===remoteWall?Math.max(oldCounter,remoteCounter)+1:next===oldWall?oldCounter+1:next===remoteWall?remoteCounter+1:0;
    this.wall=next;return this.value();
  }
}
