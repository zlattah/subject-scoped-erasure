# Related work

The research idea is **`erase(data subject)` in a chunk-deduplicated backup whose snapshots are immutable**, including when a chunk is shared or mixed. Cite these. Do not claim they do not exist.

## Cryptographic erasure of backups (ancestors)

**Boneh and Lipton, USENIX Security 1996.** *A revocable backup system.*  
https://crypto.stanford.edu/~dabo/pubs/papers/backups.pdf  
Encrypt a file; destroy the file key so every tape copy dies. No chunk sharing across files or users.

**Perlman, 2005.** *The Ephemerizer: Making Data Disappear* (Sun TR-2005-140); *File System Design with Assured Delete* (SISW 2005).  
Ephemeral keys held by a third party; expire or on-demand file/class delete. File-scoped.

**Peterson, Burns, et al., FAST 2005.** *Secure deletion for a versioning file system.*  
https://www.usenix.org/legacy/event/fast05/tech/full_papers/peterson/peterson.pdf  
Versioning FS; AONT / per-block keys so a small stub overwrite kills a version.

**Tang, Lee, Lui, Perlman, SecureComm 2010.** *FADE: Secure Overlay Cloud Storage with File Assured Deletion.*  
https://www.cse.cuhk.edu.hk/~pclee/www/pubs/securecomm10.pdf  
Policy-based file delete on S3. Overlay; not a multi-subject chunk store.

## Versioned backup + sharing (closest)

**Vrable, Savage, Voelker, FAST 2009.** *Cumulus: Filesystem Backup to the Cloud.*  
Thin-cloud backup; chunks shared **across versions**. No assured delete.

**Rahumed, Chen, Tang, Lee, Lui, ICPPW 2011.** *A Secure Cloud Backup System with Assured Deletion and Version Control* (**FadeVersion**).  
https://www.cse.cuhk.edu.hk/~pclee/www/pubs/cloudsec11.pdf  
Layered keys: `{object}_k` stored once; `{k}_s` per version. Shred `s1` to kill version V1; V2 still unwraps `k` with `s2`.  
**Solves:** delete a **version** (or file) without breaking other versions that share the object.  
**Does not solve:** two **subjects** sharing one object with independent GDPR erase; **mixed** objects; they sketch a user policy as **nested** wraps (revoke Alice ⇒ `k` dies for everyone).

This project keeps FadeVersion’s “wrap the DEK, not the payload, so share can survive one policy dying” and changes the policy axis from **version** to **subject**, with an explicit mixed-content rule.

## Physical GC and sanitization (different problem)

**Strzelczak et al., FAST 2013.** *Concurrent Deletion in a Distributed Content-Addressable Storage System with Global Deduplication.*  
https://www.usenix.org/system/files/conference/fast13/fast13-final91.pdf  
HYDRAstor: reclaim chunks with no remaining owners, concurrently. Space, not “forget a person.”

**Botelho, Shilane, Garg, Hsu, FAST 2013.** *Memory Efficient Sanitization of a Deduplicated Storage System.*  
https://www.usenix.org/conference/fast13/technical-sessions/presentation/botelho  
Data Domain: after unlink, copy live data forward and erase the old region. **Rewrites** the store. Assumes the sensitive chunk is already unreferenced.

**Reardon, Basin, Čapkun, IEEE S&P 2013.** *SoK: Secure Data Deletion.*  
https://oaklandsok.github.io/papers/reardon2013.pdf  
Threat models and why unlink ≠ delete. Use for the adversary chapter.

**Bajaj et al., CHEOPS 2023.** *Lethe: Secure Deletion by Addition.*  
Key-hierarchy rotation for fine-grained delete. Not multi-subject chunk sharing.

## Compliance in databases (same law, different unit)

**Shastri, Banakar, Wasserman, Kumar, Chidambaram, PVLDB 2020.** *Understanding and Benchmarking the Impact of GDPR on Database Systems.*  
https://vldb.org/pvldb/vol13/p1064-shastri.pdf  
Erase/TTL/audit in Redis/Postgres. Backups called out as hard; no CDC chunk owners.

**Sarkar et al.** *Purging Compliance from Database Backups by Encryption.*  
https://www.rintonpress.com/xjdi3/xjdi3-1/149-168.pdf  
Per-row/policy key buckets so a shredded key purges that record from every DB backup. Record-scoped, not chunk-scoped.

## Encrypt-to-dedup (do not mix into the claim)

**Bellare, Keelveedhi, Ristenpart, USENIX Security 2013.** *DupLESS.*  
https://www.usenix.org/system/files/conference/usenixsecurity13/sec13-paper_bellare.pdf  
Message-locked keys via an OPRF so the server can still dedup ciphertext. Confidentiality vs brute force, **not** `erase(subject)`. Same ciphertext ⇒ shared decryptability.

Convergent / message-locked encryption (Douceur; Bellare et al. MLE), SecDep, Dekey, XDedup, S2Dedup: same family.

## Industry note

**Shilane, Chiu, Huang, Wallace, HotStorage 2016.** *99 Deduplication Problems.*  
https://www.usenix.org/system/files/conference/hotstorage16/hotstorage16_shilane.pdf  
Management, chargeback, and security when chunks are shared — the class of problems this plan sits in.

Co-owned “forget this photo” schemes (for example PBCS / digital forgetting) treat **one object, many social owners**, not backup CDC.

## One-sentence positioning

Boneh: shred a **file key**. FadeVersion: shred a **version** wrap, keep shared objects for other versions. Botelho: wipe **unreferenced** chunks. DupLESS: encrypt and still **share**. Databases: shred a **row**. **This project: shred a subject when the shared unit is a chunk, the snapshot cannot be rewritten, and the chunk may be mixed.**
