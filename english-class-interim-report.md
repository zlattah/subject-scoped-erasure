# Subject-Scoped Erasure in a Deduplicated, Immutable Backup

English-class interim report (academic write-up). The working project plan is [projectplan.md](projectplan.md).

---

## Table of Contents

1. Introduction
   - 1.1 Motivation & Background Information
   - 1.2 Problem Statement
   - 1.3 Project Objectives & Scope
   - 1.4 Report Organization
2. Literature Review
   - 2.1 Cryptographic Erasure of Backups
   - 2.2 Versioned Backup and Shared Objects
   - 2.3 Physical Deletion in Deduplicated Storage
   - 2.4 Encrypted Deduplication
   - 2.5 Compliance, Databases, and Practitioner Guidance
   - 2.6 Research Gap
3. System Design *(to be completed)*
4. Methodology & Implementation *(to be completed)*
5. Experiment Results *(to be completed)*
6. References

---

## 1. Introduction

### 1.1 Motivation & Background Information

Backup products keep many recovery points affordable by **deduplicating** identical chunks across files, machines, and snapshots (Zhu et al., 2008; Shilane et al., 2016) and by locking history in **immutable** or Object-Lock vaults so a compromised network cannot encrypt or delete it: a retained snapshot must stay bit-for-bit restorable, and rewriting last week’s backup to edit one record is treated as a failure of that model. Those two properties collide with the GDPR right to erasure (Article 17): the same vault still holds last month’s mail, file shares, and laptop images, so when human resources offboard an employee or a customer asks to be forgotten, the live application can drop the account while the backup often cannot be rewritten for thirty to three hundred and sixty-five days, or years — including on multi-tenant software-as-a-service, Microsoft 365 and Google Workspace archives, and mixed objects that interleave people (one PST, one Teams site, one family album), where litigation **holds** already demand “keep this mailbox, forget Alice.” The UK ICO treats leftover backup copies as in scope and requires that they be erased or put **beyond use** until they rotate and not restored into production (ICO, 2023); the EDPB lists deletion from backups among the main practical failures and questions whether waiting for a job to age out is “without undue delay” when retention is long (EDPB, 2026). The right to erase a person is therefore established; **backup copies are where it is weakly implemented**. Live applications can drop an account; backup products are bought for deduplication and for a vault that ransomware cannot rewrite, so they do not specify cutting one person out of a shared, frozen snapshot. Operators instead wait for rotation, lock restore, edit a copy in a lab, crypto-shred an entire tenant, or refuse mailbox-remove tools while immutability is enabled (Veeam, 2018; Rubrik, 2018; Veeam, 2024). That can suffice for a seven-day backup and a single owner and fails when immutability is long, chunks are shared across people, and the file is mixed.

That collision is not confined to a textbook appliance. An enterprise ransomware vault that still restores last Tuesday also still holds a departed employee’s laptop image and mailbox for the Object-Lock window: human resources can disable the account while an administrator restore reconstitutes the diary, the PST, and the HR export (Veeam, 2018; Rubrik, 2018). Microsoft 365 and Google Workspace archives, and multi-tenant software-as-a-service backups, pack many mailboxes or customers into one deduplicated pool, so forgetting one person must not crypto-shred neighbours who still have a right to restore. Shared Outlook PSTs, Teams sites, legal-matter mailboxes, and family or company photo libraries are mixed objects: one file contains Alice and Bob, and unlinking Alice’s catalogue does not remove her messages or her likeness from Bob’s restore. eDiscovery already requires the opposite order of operations — keep this mailbox under a litigation hold, forget Alice everywhere else — so erase must wait, and restore must say that she is still in the held snapshot rather than pretend she is gone. This project is the store that setting would need: subject-scoped erase that does not silently rewrite frozen snapshots and does not blind other people who still share bytes.

### 1.2 Problem Statement

Existing backup designs say how to delete a file or an old recovery point, not how to forget a person. Surveys of distributed deduplication still organise the field around splitting data, finding copies, restore, and reclaiming unused space (Fu et al., 2025). They do not treat a data subject as a first-class delete unit.

Three rules collide in the same vault. Sharing stores identical data once, so two people who back up the same installer have one copy on disk: dropping one person’s backup index leaves the bytes, and destroying the encryption key on that copy blinds the other person. Immutability forbids rewriting a frozen recovery point to cut someone out. Erasure still requires that person’s data to be unrecoverable from every leftover copy, including backups that also hold someone else’s files. Existing answers miss that combination. Nested key wrapping, as sketched in FadeVersion (Rahumed et al., 2011), makes the object unreadable for everyone when any one person is forgotten. Garbage collection only frees data that nobody still uses (Strzelczak et al., 2013). Physically wiping unused regions rewrites the store (Botelho et al., 2013). Practitioner guidance tells operators not to edit the vault at all (ProBackup, 2024; Wolf-Tech, n.d.).

The hard part depends on the data. Unique files belong to one person and can be forgotten by destroying that person’s keys. Identical public files (a shared installer) may stay on disk if others can still restore and the forgotten person cannot restore their own copy. Mixed files — one mailbox, one group photograph, one spreadsheet with two employees — cannot stay as one shared encrypted blob if one person must disappear and the other must still open something useful. A legal hold delays that destruction and must be obvious, because restore may still return the forgotten person while the hold is live.

This project therefore asks for a store and a key policy such that forgetting a person makes their personal data unrecoverable from every frozen snapshot, including ones that share bytes with others, while everyone else who is entitled can still restore, holds can delay destruction without hiding that fact, and extra space can be measured against never sharing across people. The leftover is not a new hash. It is forgetting a person when storage is shared, snapshots cannot be rewritten, content may mix people, and a hold may block the delete.

### 1.3 Project Objectives & Scope

This project aims to design and implement a laptop-scale backup store that treats `erase(S)` as a first-class operation under deduplication and immutability, and to evaluate that design on labelled files, mixed containers, holds, and a multi-tenant ingest mix. Rather than relying on “beyond use until rotation” or tenant-wide key destruction, the store will classify regions as unique, identical, or mixed, wrap data-encryption keys per entitled subject, parse shared mailboxes and photo libraries into inner objects, and pin keys when a hold is live.

The primary objectives are as follows.

1. Specify the problem and a glossary (subject, chunk, recipe, snapshot, owner set, unique / identical / mixed, cryptographic erasure, OR-wrap versus AND-wrap, copy-out, hold, deferred erase) so the claim is not confused with version delete or physical overwrite.
2. Implement ingest, restore, `erase(S)`, `hold` / `release`, owner sets, and the wrap modes in one pipeline, with a mutable key store and an append-only chunk log.
3. Parse one PST or mbox and one two-subject photo library so erase runs on messages, attachments, and photos rather than on the whole file.
4. Measure unique bytes, restore success or failure, and the recoverability window while a hold is live, first on a synthetic two-subject corpus and then on a multi-tenant ingest trace or a named public substitute.
5. Write the comparison so a leak under mixed OR-wrap, a space cost under never-share, and a delay under hold are expected outcomes, not surprises.

**In scope.** Subject-scoped erase in a chunk-addressed backup; unique, identical, and mixed classes, including mixed containers; OR-wrap, AND-wrap, no cross-user share, and copy-out as baselines; holds and deferred shred; a synthetic corpus and a tenant-labelled trace; a leftover-store threat model (remaining keys plus the chunk log). FadeVersion-style version delete is a solved baseline, not the claim.

**Out of scope.** A new content-defined chunking algorithm; legal advice or a production PII classifier (labels and header heuristics are inputs); SGX, blockchain, or hardware security modules as the contribution; encrypted-deduplication brute-force resistance (DupLESS); physical drive overwrite as the only delete mechanism; perceptual near-duplicate matching.

### 1.4 Report Organization

The remainder of this plan is organised as follows. Section 2 reviews cryptographic erasure, versioned sharing, physical sanitisation, encrypted deduplication, and compliance practice, and states the gap. Section 3 will present the system design (chunk log, recipes, key store, and class rules). Section 4 will describe methodology and implementation. Section 5 will report experiments. Section 6 lists the references used in this version. Sections 3–5 are reserved and are not filled in this revision.

---

## 2. Literature Review

This section reviews the lines of work that already touch deletion, sharing, or backups. Each line solves part of the setting in Section 1 and leaves a restriction that the present project takes as the leftover. The aim is to place the claim honestly: several techniques exist; the combination of subject erase, shared chunks, immutable snapshots, mixed containers, and holds does not.

### 2.1 Cryptographic Erasure of Backups

The idea of making backup media unreadable by destroying a key, rather than overwriting the tape, is old. Boneh and Lipton (1996) presented a revocable backup system in which each file is encrypted under a file key; forgetting the file is implemented by deleting that key so every tape copy becomes useless. The design does not share payloads across files or users, so there is no second subject who still needs the same ciphertext. Perlman (2005a, 2005b) concentrated ephemeral keys in an “ephemerizer” and described a file system with expiration, on-demand file delete, and class keys.

Peterson et al. (2005) added secure deletion of individual versions to a versioning file system (ext3cow). A versioning file system does not keep a full extra copy of every file for every snapshot. It uses copy-on-write. If snapshots are taken each day of the week, Wednesday does not duplicate Tuesday’s unchanged bytes: those blocks are stored once, and both days’ versions hold pointers to them. What is saved for each day is therefore not a self-contained “Tuesday file” on disk, but an inode — a metadata record that lists, for that version, which data blocks to read. Unchanged blocks are shared. Only blocks that actually changed when the next snapshot was taken receive a new physical copy.

Deleting only Tuesday is then awkward for a structural reason, not a bookkeeping oversight. There is no single Tuesday image to wipe. Tuesday’s bytes sit among other versions. Overwriting a shared data block would also destroy Wednesday’s restore of the same block. Overwriting only the blocks unique to Tuesday is possible in principle, but copy-on-write scatters those blocks, so a multi-pass overwrite of the data plane is slow, and the system must still know which blocks are unshared. Disposing of one encryption key per version, in the style of Boneh and Lipton (1996), also fails here. If Tuesday and Wednesday share a block, that version key cannot be forgotten without blinding Wednesday. A separate secret key for every shared block would work but, Peterson et al. argue, quickly becomes unmanageable.

Their solution keeps the pointer lists and adds a small extra field per block, called a stub. Each data block is put through a keyed transform that outputs two pieces: a ciphertext of the same size as the original block, which is written to disk as the data block, and a short stub (128 bits in their all-or-nothing scheme), which is stored in metadata next to the inode’s block map. Stubs from many blocks are packed into contiguous metadata blocks so that overwriting one 4 KB region of stubs can delete a megabyte of file data even when the corresponding data blocks are not contiguous.

A stub is easy to confuse with a key, but it is not a secret the operator hides in a key server. Peterson et al. present two transforms. In the all-or-nothing scheme, inspired by Rivest’s all-or-nothing transform (1997), recovering any of the plaintext requires the entire transformed output. The stub is an expansion of that ciphertext: a public fragment split off into metadata. Without it, the on-disk block cannot be inverted. In the random-key scheme, each block is encrypted under a fresh per-block key, and that key is wrapped under the file’s encryption key; the wrapped per-block key is the stub. That second stub is closer to a key, but it still lives in ordinary file-system metadata, not in a separate wrap store. In both designs, Peterson et al. state that stubs reveal nothing about the file key or the data and may be stored on the same disk. While a version is live, anyone who can read the inode can read the stub. A file-level key still encrypts the disk and provides authenticated encryption while it remains private. The stub’s job is different: even if that key is later revealed, for example by subpoena, a block whose stub has already been overwritten stays unrecoverable.

Secure deletion of Tuesday is then a metadata overwrite rather than a sweep of Tuesday’s data blocks. The system overwrites the stubs that belong to Tuesday’s inode. Shared, unchanged blocks still have stub copies in Wednesday’s inode, so those data blocks remain readable from Wednesday. Blocks that only Tuesday needed had stubs only in Tuesday’s inode; once those stubs are overwritten, those blocks cannot be inverted. Copy-on-write already isolates the unique pieces. There is no extra “mark only Tuesday” pass beyond writing new blocks and new stubs for the data Tuesday actually changed. Overwriting a packed set of small stubs therefore destroys the recoverability of one version without punching the shared payload out of later versions.

That is still version-scoped deletion, not subject-scoped erase. Peterson’s unit is a file version after a retention period (their motivating setting is regulatory record-keeping). It is not a person who shares bytes with someone else inside the same snapshot. Overwriting Tuesday’s stubs does not punch Alice out of a mailbox that Bob must still restore on Wednesday.

Tang et al. (2010) built FADE as an overlay on cloud object storage: files are encrypted under policy keys, and revoking a policy shreds the corresponding control key.

These systems establish cryptographic erasure as the only practical way to “delete” data that the operator is not allowed to rewrite. They also establish the architectural split this project keeps: an immutable or outsourced data plane and a small, mutable key store. Their delete unit is a **file**, a **version**, or a **policy**, not a data subject who may share a chunk with someone else. If two people encrypt the same bytes under one key, shredding that key blinds both. If each person has a separate file key, there is no space sharing. The present store therefore reuses shredding and changes the policy axis.

### 2.2 Versioned Backup and Shared Objects

Thin-cloud backup systems such as Cumulus split files into chunks and upload only chunks that did not appear in an earlier snapshot (Vrable et al., 2009). Cross-**version** sharing is the ordinary backup win: Wednesday reuses Tuesday’s unchanged objects. Cumulus does not provide assured deletion. Rahumed et al. (2011) observed that stacking a version-control system and an assured-deletion system in either order breaks one of the two features. If versions are built first and then encrypted under a per-version key, shredding the old version’s key also hides objects that the new version still references. If files are encrypted first under different keys, the versioning layer cannot see that two ciphertexts are the same bytes.

Their system, FadeVersion, fixes that incompatibility with layered keys. Each object is encrypted under a random data key `k`; `k` is then encrypted under a per-version (or per-policy) control key `s`. The ciphertext `{object}_k` is stored once. Deleting version V1 shreds `s1`. Version V2 still unwraps `k` with `s2`. That is the correct pattern for “forget a snapshot, keep the shared payload for later snapshots.” FadeVersion even sketches a user-based policy as one of several nested wraps. Nested wrapping is conjunctive: if any listed policy is revoked, `k` dies. Forgetting Alice then makes the object unreadable for Bob. The paper does not evaluate two subjects who share one object and must be erased independently, and it does not treat mixed content inside one mailbox or photograph. The present project keeps the layered-key idea and moves the control key from **version** to **subject**, with an explicit rule that mixed payloads are not OR-wrapped as a whole.

### 2.3 Physical Deletion in Deduplicated Storage

When a file is unlinked, a content-addressable store still holds chunks that other files reference. Strzelczak et al. (2013) describe concurrent deletion and reference counting in HYDRAstor so that chunks with no remaining owners can be reclaimed while user I/O continues. Botelho et al. (2013) treat **sanitisation** of a Data Domain system: after sensitive files are deleted, live chunks are copied forward and the old region is erased so leftover unique data is gone from the device. Their contribution is a memory-efficient perfect-hash structure for tracking references at appliance scale. Reardon et al. (2013) systematise secure deletion across interfaces and adversaries, and emphasise that unlinking a file is not the same as making its bytes unrecoverable. Bajaj et al. (2023) rotate a key hierarchy (“deletion by addition”) so that fine-grained secure delete does not require in-place overwrite of a large medium.

These papers matter because they show that **physical** reclaim in a deduplicated log is a rewrite of the store and assumes the sensitive chunk is already unreferenced. They do not define a subject. A chunk that Bob still needs cannot be sanitised to forget Alice. A WORM vault that forbids copy-forward cannot run Data Domain sanitisation as the erasure mechanism. This project therefore uses cryptographic shred for unrecoverability and treats physical garbage collection as optional and possibly forbidden.

### 2.4 Encrypted Deduplication

If clients encrypt conventionally, a storage server cannot detect duplicate files. Convergent and message-locked encryption derive the key from the plaintext so identical files produce identical ciphertexts (Douceur et al., 2002; Bellare et al., 2013a). DupLESS strengthens that construction with an oblivious PRF and a key server so that offline brute force on predictable files is harder (Bellare et al., 2013b). Later systems (SecDep, Dekey, XDedup, S2Dedup) vary key management and trusted execution. Fu et al. (2025) still list secure deduplication as an open direction, largely in this confidentiality-versus-share sense.

The present claim is easy to confuse with that literature and must not be. Encrypted deduplication answers “can the server still save space when data are encrypted?” It does not answer `erase(S)`. If two users produce the same ciphertext so that the server can share it, they necessarily share the ability to decrypt that blob. Destroying one user’s key does not make the ciphertext meaningless unless remaining users are re-encrypted. That is the identical-versus-mixed distinction, not a new MLE scheme.

### 2.5 Compliance, Databases, and Practitioner Guidance

Database and systems papers have begun to treat GDPR as a workload. Shastri et al. (2020) retrofit Redis and PostgreSQL with timely delete, TTL, and audit, and note that backups remain the painful leftover. Sarkar et al. (2022) assign encryption keys to policy buckets so that shredding a key purges a record from every database backup without editing the backup file. The delete unit is a **row**, not a CDC chunk, and mixed files do not arise.

Industry and practitioner writing has discussed backup erasure continuously since 2018. Rubrik (2018) states that the right to erasure clashes with uneditable backups and recommends short SLAs and selective restore. Veeam (2018) describes staged restore: mount a copy in a lab, delete the forgotten subject there, then return the rest to production. Backup vendors’ own tools that remove one user’s mailbox from a repository refuse to run when object-storage immutability is enabled (Veeam, 2024). Compliance blogs repeat the ICO “beyond use” recipe and advise against surgical rewrite of binary backups (myeDPO, 2018; ProBackup, 2024; Wolf-Tech, n.d.). Engineering posts on crypto-shredding recommend a per-user or per-tenant key and warn that backing up the key store undoes shred (Cidre, 2026; Encryption Consulting, 2024). A Law StackExchange discussion of GDPR on deduplicated storage concludes that erase should drop the **logical** copy, not the shared physical block, or the other uploader is breached (Law SE, 2023). Product documentation for tenant-scoped shred states that destroying a tenant key kills every backup of that tenant; forgetting one row without destroying the tenant is left to retention expiry (pg_hardstorage, 2025).

This writing is evidence that the problem is real. It is also evidence that the accepted answer is process (do not restore Alice; wait for rotation) or coarse shred (one key per tenant). It does not specify unique / identical / mixed classes, inner-object erase of a PST or photo library, or a hold that pins keys and measures the recoverability window.

### 2.6 Research Gap

Boneh and Lipton shred a file key. FadeVersion shreds a version wrap and keeps shared objects for other versions. Botelho et al. wipe unreferenced chunks by rewriting the log. DupLESS encrypts so the server can still share. Database work shreds a row. Practitioner guidance tells operators not to edit the vault. Shilane et al. (2016) listed management, chargeback, and security on shared chunks as under-studied product problems; subject-scoped erase under immutability sits in that class.

The gap this project takes is therefore: **`erase(data subject)` when the shared unit is a chunk, retained snapshots cannot be rewritten, a chunk may be mixed, and a hold may delay shred.** The contribution is a store and a policy, with measurements of space, restore, and unrecoverability, not a new fingerprint function.

---

## 3. System Design

*To be completed.*

---

## 4. Methodology & Implementation

*To be completed.*

---

## 5. Experiment Results

*To be completed.*

---

## 6. References

Bellare, M., Keelveedhi, S. and Ristenpart, T. (2013a) ‘Message-locked encryption and secure deduplication’, *Advances in Cryptology – EUROCRYPT 2013*. Springer, pp. 296–312.

Bellare, M., Keelveedhi, S. and Ristenpart, T. (2013b) ‘DupLESS: server-aided encryption for deduplicated storage’, *22nd USENIX Security Symposium*. USENIX, pp. 179–194.

Bajaj, S. et al. (2023) ‘Lethe: secure deletion by addition’, *Proceedings of the 3rd Workshop on Challenges and Opportunities of Efficient and Performant Storage Systems (CHEOPS ’23)*. ACM.

Boneh, D. and Lipton, R. (1996) ‘A revocable backup system’, *6th USENIX Security Symposium*. USENIX, pp. 91–96.

Botelho, F.C., Shilane, P., Garg, N. and Hsu, W. (2013) ‘Memory efficient sanitization of a deduplicated storage system’, *11th USENIX Conference on File and Storage Technologies (FAST ’13)*. USENIX, pp. 81–94.

Cidre, A. (2026) ‘Don’t delete the row. Delete the key’. Available at: https://adriacidre.com/blog/dont-delete-the-row-delete-the-key/ (Accessed: 19 September 2026).

Douceur, J.R., Adya, A., Bolosky, W.J., Simon, D. and Theimer, M. (2002) ‘Reclaiming space from duplicate files in a serverless distributed file system’, *Proceedings of the 22nd International Conference on Distributed Computing Systems (ICDCS)*. IEEE, pp. 617–624.

Encryption Consulting (2024) ‘Get familiar with the new concept of crypto-shredding’. Available at: https://www.encryptionconsulting.com/introduction-to-crypto-shredding/ (Accessed: 19 September 2026).

European Data Protection Board (2026) *Coordinated Enforcement Action: implementation of the right to erasure by controllers*. Brussels: EDPB.

Fu, Y., Su, J., Ning, J., Wu, J., Lu, Y. and Xiao, N. (2025) ‘Distributed data deduplication for big data: a survey’, *ACM Computing Surveys*, 58(3). doi: 10.1145/3735508.

Information Commissioner’s Office (2023) *Right to erasure*. Available at: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/ (Accessed: 19 September 2026).

Law StackExchange (2023) ‘How does GDPR’s right to erasure apply to deduplicated storage?’. Available at: https://law.stackexchange.com/questions/91793/how-does-gdprs-right-to-erasure-apply-to-deduplicated-storage (Accessed: 19 September 2026).

myeDPO (2018) ‘Right to erasure (RTBF) from backups’. Available at: https://www.myedpo.com/post/2018/08/21/right-to-erasure-rtbf-from-backups (Accessed: 19 September 2026).

Perlman, R. (2005a) *The Ephemerizer: making data disappear*. Sun Microsystems Technical Report TR-2005-140.

Perlman, R. (2005b) ‘File system design with assured delete’, *Third IEEE International Security in Storage Workshop (SISW)*. IEEE.

Peterson, Z.N.J., Burns, R., Herring, J., Stubblefield, A. and Rubin, A.D. (2005) ‘Secure deletion for a versioning file system’, *4th USENIX Conference on File and Storage Technologies (FAST ’05)*. USENIX.

pg_hardstorage (2025) ‘GDPR Article 17 — crypto-shred’. Available at: https://docs.pghardstorage.org/compliance/gdpr-art-17-crypto-shred/ (Accessed: 19 September 2026).

ProBackup (2024) ‘GDPR deletion requests & backups: how to stay compliant’. Available at: https://www.probackup.io/blog/gdpr-and-backups-how-to-handle-deletion-requests (Accessed: 19 September 2026).

Rahumed, A., Chen, H.C.H., Tang, Y., Lee, P.P.C. and Lui, J.C.S. (2011) ‘A secure cloud backup system with assured deletion and version control’, *International Conference on Parallel Processing Workshops*. IEEE, pp. 160–167.

Reardon, J., Basin, D. and Čapkun, S. (2013) ‘SoK: secure data deletion’, *2013 IEEE Symposium on Security and Privacy*. IEEE, pp. 301–315.

Rivest, R.L. (1997) ‘All-or-nothing encryption and the package transform’, *Fast Software Encryption*. Springer, pp. 210–218.

Rubrik (2018) ‘Aligning your data protection strategy with GDPR’. Available at: https://www.rubrik.com/blog/technology/18/4/gdpr-data-protection-strategy (Accessed: 19 September 2026).

Sarkar, S. et al. (2022) ‘Purging compliance from database backups by encryption’, *Journal of Digital Information Management* / companion technical report. Available at: https://www.rintonpress.com/xjdi3/xjdi3-1/149-168.pdf (Accessed: 19 September 2026).

Shastri, S., Banakar, V., Wasserman, M., Kumar, A. and Chidambaram, V. (2020) ‘Understanding and benchmarking the impact of GDPR on database systems’, *Proceedings of the VLDB Endowment*, 13(7), pp. 1064–1077.

Shilane, P., Chiu, M., Huang, Y. and Wallace, G. (2016) ‘99 deduplication problems’, *8th USENIX Workshop on Hot Topics in Storage and File Systems (HotStorage ’16)*. USENIX.

Strzelczak, P. et al. (2013) ‘Concurrent deletion in a distributed content-addressable storage system with global deduplication’, *11th USENIX Conference on File and Storage Technologies (FAST ’13)*. USENIX, pp. 161–174.

Tang, Y., Lee, P.P.C., Lui, J.C.S. and Perlman, R. (2010) ‘FADE: secure overlay cloud storage with file assured deletion’, *SecureComm 2010*. Springer, pp. 380–397.

Veeam (2018) ‘Take your business beyond availability with DataLabs’. Available at: https://www.veeam.com/blog/datalabs-secure-staged-restore.html (Accessed: 19 September 2026).

Veeam (2024) ‘Remove-VBOEntityData’. *Veeam Backup for Microsoft 365 PowerShell Reference*. Available at: https://helpcenter.veeam.com/docs/vbo365/powershell/remove-vboentitydata.html (Accessed: 19 September 2026).

Vrable, M., Savage, S. and Voelker, G.M. (2009) ‘Cumulus: filesystem backup to the cloud’, *7th USENIX Conference on File and Storage Technologies (FAST ’09)*. USENIX.

Wolf-Tech (n.d.) ‘GDPR right-to-erasure engineering: actually deleting users from complex SaaS systems’. Available at: https://wolf-tech.io/blog/gdpr-right-to-erasure-engineering-actually-deleting-users-from-complex-saas-systems (Accessed: 19 September 2026).

Zhu, B., Li, K. and Patterson, H. (2008) ‘Avoiding the disk bottleneck in the Data Domain deduplication file system’, *6th USENIX Conference on File and Storage Technologies (FAST ’08)*. USENIX, pp. 269–282.
