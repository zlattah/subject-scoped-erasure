# Subject-Scoped Erasure in a Deduplicated, Immutable Backup

Department of Computer Science  
BSCCS Final Year Project 202X–202X  
Interim Report (Volume 1 of 1)

---

## Table of Contents

1. Introduction
   - 1.1 Motivation & Background Information
   - 1.2 Problem Statement
   - 1.3 Project Objectives & Scope
   - 1.4 Report Organization
2. Literature Review
   - 2.1 Review of Cryptographic Erasure of Backups
3. System Design
4. Methodology & Implementation
5. Experiment Results
6. References

---

## 1. Introduction

### 1.1 Motivation & Background Information

Backup systems have become the core of protection against hardware failures or ransomware through their recovery checkpoints. To make these backups more affordable, deduplication solutions are often introduced across files, machines and checkpoints. Deduplication here means identical bytes are only stored once and referenced many times, with different access points: two laptops that back up the same installer, or Tuesday and Wednesday snapshots that share the files that did not change, all point at one physical copy. In parallel, those same products also offer immutable vaults so that a potential attacker cannot corrupt these backups, thus after an attack we can go back to a previous version. Last Tuesday must still restore bit-for-bit. Rewriting that day to edit one record is treated as a failure of the protection model, not as a feature.

These two properties collide with a third requirement — erasure of a data subject. This condition has become standard since the General Data Protection Regulation (GDPR) and similar policies have highlighted the right of a person “to be forgotten”. When deleting a person’s data the backup vault cannot be rewritten, usually for at least a year. The live application can drop an account in minutes; leftover copies on the vault are still in scope. The UK Information Commissioner’s Office requires that those copies be erased or put beyond use until they rotate and not restored into production (ICO, 2023); the European Data Protection Board lists deletion from backups among the main practical failures (EDPB, 2026). This project is focused on a subject-scoped erase that does not silently overwrite snapshots and does not blind other people who reference the same bytes as the deleted subject.

That collision shows up in ordinary operations, not only in a textbook appliance.

A first example is employee offboarding on an enterprise ransomware vault. Human resources disable the account. The Object-Lock window still holds last month’s laptop image and mailbox, because those checkpoints must remain restorable if ransomware hits tomorrow. An administrator restore can reconstitute the diary, the mail file, and the HR export of a person who is supposed to be gone.

A second example is sharing. Alice and Bob both back up the same public installer. Deduplication stores it once. Dropping Alice’s backup index does not remove the bytes. Destroying the one encryption key on that copy would also prevent Bob from restoring a file he is still entitled to. The opposite case is a mixed object: one Outlook mailbox, one Teams site, or one family photo album that contains both people. Unlinking Alice’s catalogue does not take her messages or her likeness out of Bob’s restore. The bytes sit in the same file.

A third example is multi-tenant archives (Microsoft 365, Google Workspace, software-as-a-service backups). Many mailboxes or customers share one deduplicated pool. Crypto-shredding a whole tenant to forget Alice blinds neighbours who still have a right to restore. On the same vault, a litigation hold can reverse the order of operations: keep this mailbox for a legal matter, forget Alice everywhere else. Erase has to wait, and restore has to say that she is still in the held snapshot rather than pretend she is gone.

What operators do today is wait for the checkpoint to age out, lock restore so Alice is not rolled back into production, mount a copy in a lab and edit it, shred an entire tenant, or refuse mailbox-remove tools while immutability is enabled. That can suffice for a short retention and a single owner. It fails when the lock lasts months, chunks are shared across people, the file is mixed, or a hold says keep the mailbox. The store this project aims at is the one that setting would need.

### 1.2 Problem Statement

Existing backup designs say how to delete a file or an old recovery point, not how to forget a person. Three rules meet in the same vault. Sharing stores identical data once, so two people who back up the same installer have one copy on disk: dropping one person’s index leaves the bytes, and destroying the encryption key on that copy blinds the other person. Immutability forbids rewriting a frozen checkpoint to cut someone out. Erasure still requires that person’s data to be unrecoverable from every leftover copy, including backups that also hold someone else’s files.

The hard part depends on the data. Unique files (a private diary) belong to one person and can be forgotten by destroying that person’s keys. Identical public files (a shared installer) may stay on disk if others can still restore and the forgotten person cannot restore their own copy. Mixed files — one mailbox, one group photograph, one spreadsheet with two employees — cannot stay as one shared encrypted blob if one person must disappear and the other must still open something useful. A legal hold delays that destruction and must be visible, because restore may still return the forgotten person while the hold is live.

This project therefore asks for a store and a key policy such that forgetting a person makes their personal data unrecoverable from every frozen snapshot, including ones that share bytes with others, while everyone else who is entitled can still restore, holds can delay destruction without hiding that fact, and extra space can be measured against never sharing across people. The leftover is not a new hash. It is forgetting a person when storage is shared, snapshots cannot be rewritten, content may mix people, and a hold may block the delete.

### 1.3 Project Objectives & Scope

This project aims to design and implement a laptop-scale backup store that treats forgetting a person, `erase(S)`, as a first-class operation under deduplication and immutability, and to evaluate that design on labelled files, mixed containers, holds, and a multi-tenant ingest mix. Rather than relying on “beyond use until rotation” or tenant-wide key destruction, the store will classify regions as unique, identical, or mixed, wrap data-encryption keys per entitled subject, parse shared mailboxes and photo libraries into inner objects, and pin keys when a hold is live.

The primary objectives are as follows.

1. Specify the problem and a glossary (subject, chunk, recipe, snapshot, owner set, unique / identical / mixed, cryptographic erasure, OR-wrap versus AND-wrap, copy-out, hold, deferred erase) so the claim is not confused with version delete or physical overwrite.
2. Implement ingest, restore, `erase(S)`, hold / release, owner sets, and the wrap modes in one pipeline, with a mutable key store and an append-only chunk log.
3. Parse one mailbox format (mbox, or Outlook PST if feasible) and one two-subject photo library so erase runs on messages, attachments, and photos rather than on the whole file.
4. Measure unique bytes, restore success or failure, and the recoverability window while a hold is live, first on a synthetic two-subject corpus and then on a multi-tenant ingest trace or a named public substitute.
5. Write the comparison so a leak under mixed OR-wrap, a space cost under never-share, and a delay under hold are expected outcomes, not surprises.

In scope. Subject-scoped erase in a chunk-addressed backup; unique, identical, and mixed classes, including mixed containers; OR-wrap, AND-wrap, no cross-user share, and copy-out as baselines; holds and deferred shred; a synthetic corpus and a tenant-labelled trace; a leftover-store threat model (remaining keys plus the chunk log). Deleting a version while keeping later versions, as in FadeVersion, is a solved baseline, not the claim.

Out of scope. A new content-defined chunking algorithm; legal advice or a production person-identifying classifier (labels and header heuristics are inputs); hardware security modules, SGX, or blockchain as the contribution; encrypted-deduplication brute-force resistance; physical drive overwrite as the only delete mechanism; perceptual near-duplicate matching.

This interim report covers the motivation, the problem, and the first part of the literature review. System design, implementation, and experiments are left for later submissions.

### 1.4 Report Organization

The remainder of this report is organised as follows. Section 2 reviews cryptographic erasure of backups and states how those systems stop short of subject-scoped erase. Section 3 will present the system design. Section 4 will describe methodology and implementation. Section 5 will report experiments. Section 6 lists the references used in this version. Sections 3–5 are reserved and are not filled in this revision.

---

## 2. Literature Review

This section is a survey of related works in the domains of deletion, sharing, and backup. Each of these areas addresses a portion of the problem defined in Section 1. The purpose is to present the problem honestly: there are many existing solutions, however, there is not this combination of conditions and techniques.

### 2.1 Review of Cryptographic Erasure of Backups

The concept of making data unusable through key destruction, rather than writing over them, comes from the 1996 paper by Boneh and Lipton. In their work, they present a revocable backup scheme wherein each file is encrypted with respect to a file key and forgetting the file is implemented by deleting that key, whenever the user decides to do so. However, if two users share the same file, deleting its key would blind one of the users, which is a key concern in our case.

Perlman (2005) introduces a third party, the “ephemerizer”, that holds short-lived keys — ephemeral keys. When their expiry time passes, the ephemerizer automatically destroys those keys and all of the ciphertext encrypted under those keys becomes unreadable. This solution is still file-scoped and not subject-scoped, but it is a first step toward the idea that leftover copies can be forgotten by destroying a key rather than by wiping the disk.

Peterson et al. (2005) adds a secure deletion to a versioning file system. A versioning file system uses copy-on-write, meaning it does not duplicate the bytes shared across different versions. So for each version we save pointers to data blocks to read. Unchanged blocks are shared, changed ones get a new copy. Let’s say we have snapshots for every day of the week. If we delete only Tuesday that’s awkward because its bytes are shared among versions, there’s no single ‘Tuesday file’ to wipe. Overwriting only the blocks unique to Tuesday is possible, but since they are scattered, it would be slow and we’d need to know which blocks are unshared. Disposing of one key per version in the style of Boneh and Lipton (1996) would also fail since if two versions share a block, that key cannot be forgotten without blinding one version. A separate key for every shared block would work but it quickly becomes unmanageable (Peterson et al., 2005).

The solution proposed by Peterson et al. (2005) keeps history in pointer lists plus a small stub per block. Each block is put through an all-or-nothing transform (AONT) that outputs a block of the same size which is written to the disk, plus a short stub (128 bits) written as metadata next to the block pointers. Because of the AONT the files cannot be recovered without their stubs, thus overwriting a small contiguous piece of metadata containing stubs can delete megabytes of file data even when the corresponding blocks are not contiguous. That is still version-scoped deletion, not subject-scoped. The unit is a file version, not a person who shares bytes with someone else.

In the work of Tang et al. (2010) FADE is constructed as an overlay of an existing cloud storage. The premise is that cloud is not to be trusted: it may keep extra copies after a delete request and the client does not know how many copies there are and where they are stored. FADE uses the same idea of not relying on the storage provider to delete the bytes, so it makes the bytes unreadable by destroying the keys. Encrypted files stay on the cloud, and control keys live at a separate key manager, so revoking a policy never requires a rewrite of the cloud data.

These systems set up cryptographic deletion as the only feasible means of deleting data which is forbidden from being overwritten by the operator. They also set up the architectural separation that this project maintains between an immutable or delegated data plane and a small mutable key store. What they take as the unit of delete can be a file, a version, or a policy, never a data subject. And more specifically, never a data subject that can share chunks with another.

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

[1] Bellare, M., Keelveedhi, S. and Ristenpart, T. (2013a) ‘Message-locked encryption and secure deduplication’, *Advances in Cryptology – EUROCRYPT 2013*. Springer, pp. 296–312.

[2] Bellare, M., Keelveedhi, S. and Ristenpart, T. (2013b) ‘DupLESS: server-aided encryption for deduplicated storage’, *22nd USENIX Security Symposium*. USENIX, pp. 179–194.

[3] Bajaj, S. et al. (2023) ‘Lethe: secure deletion by addition’, *Proceedings of the 3rd Workshop on Challenges and Opportunities of Efficient and Performant Storage Systems (CHEOPS ’23)*. ACM.

[4] Boneh, D. and Lipton, R. (1996) ‘A revocable backup system’, *6th USENIX Security Symposium*. USENIX, pp. 91–96.

[5] Botelho, F.C., Shilane, P., Garg, N. and Hsu, W. (2013) ‘Memory efficient sanitization of a deduplicated storage system’, *11th USENIX Conference on File and Storage Technologies (FAST ’13)*. USENIX, pp. 81–94.

[6] Cidre, A. (2026) ‘Don’t delete the row. Delete the key’. Available at: https://adriacidre.com/blog/dont-delete-the-row-delete-the-key/ (Accessed: 19 September 2026).

[7] Douceur, J.R., Adya, A., Bolosky, W.J., Simon, D. and Theimer, M. (2002) ‘Reclaiming space from duplicate files in a serverless distributed file system’, *Proceedings of the 22nd International Conference on Distributed Computing Systems (ICDCS)*. IEEE, pp. 617–624.

[8] Encryption Consulting (2024) ‘Get familiar with the new concept of crypto-shredding’. Available at: https://www.encryptionconsulting.com/introduction-to-crypto-shredding/ (Accessed: 19 September 2026).

[9] European Data Protection Board (2026) *Coordinated Enforcement Action: implementation of the right to erasure by controllers*. Brussels: EDPB.

[10] Fu, Y., Su, J., Ning, J., Wu, J., Lu, Y. and Xiao, N. (2025) ‘Distributed data deduplication for big data: a survey’, *ACM Computing Surveys*, 58(3). doi: 10.1145/3735508.

[11] Information Commissioner’s Office (2023) *Right to erasure*. Available at: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/ (Accessed: 19 September 2026).

[12] myeDPO (2018) ‘Right to erasure (RTBF) from backups’. Available at: https://www.myedpo.com/post/2018/08/21/right-to-erasure-rtbf-from-backups (Accessed: 19 September 2026).

[13] Perlman, R. (2005a) *The Ephemerizer: making data disappear*. Sun Microsystems Technical Report TR-2005-140.

[14] Perlman, R. (2005b) ‘File system design with assured delete’, *Third IEEE International Security in Storage Workshop (SISW)*. IEEE.

[15] Peterson, Z.N.J., Burns, R., Herring, J., Stubblefield, A. and Rubin, A.D. (2005) ‘Secure deletion for a versioning file system’, *4th USENIX Conference on File and Storage Technologies (FAST ’05)*. USENIX.

[16] Rahumed, A., Chen, H.C.H., Tang, Y., Lee, P.P.C. and Lui, J.C.S. (2011) ‘A secure cloud backup system with assured deletion and version control’, *International Conference on Parallel Processing Workshops*. IEEE, pp. 160–167.

[17] Tang, Y., Lee, P.P.C., Lui, J.C.S. and Perlman, R. (2010) ‘FADE: secure overlay cloud storage with file assured deletion’, *SecureComm 2010*. Springer, pp. 380–397.
