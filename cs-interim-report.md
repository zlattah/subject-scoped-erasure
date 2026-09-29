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

Existing backup designs delete a file or a checkpoint, not a person. Sharing stores identical bytes once: dropping one index leaves the data, and destroying the one key blinds the other person. Immutability forbids rewriting a frozen checkpoint. Unique files can be forgotten with one person’s keys; identical public files may stay if others can still restore; mixed files cannot remain one shared blob. This project asks for a store and a key policy that makes a person unrecoverable from every frozen snapshot without blinding everyone else, including when a hold delays the delete.

### 1.3 Project Objectives & Scope

The aim is a laptop-scale backup store that can forget one person under deduplication and immutability, and measure that design on labelled files, mixed containers, and holds.

1. Specify the problem and terms so erase of a person is not confused with deleting a file or a version.
2. Implement ingest, restore, erase, and hold in one pipeline (mutable key store, append-only chunk log).
3. Parse a mailbox and a two-subject photo library so erase runs on inner objects, not only whole files.
4. Measure leftover bytes, restore, and the hold window on a synthetic corpus.
5. Treat mixed leaks, never-share extra space, and hold delay as expected outcomes, not surprises.

In scope: subject-scoped erase; unique / identical / mixed; wrap baselines; holds; a leftover-store attacker. Out of scope: a new chunking algorithm, legal classification, and physical overwrite as the only delete. Design, implementation, and experiments are left for later reports.

### 1.4 Report Organization

Section 2 reviews cryptographic erasure of backups. Sections 3–5 (design, method, experiments) are reserved. Section 6 lists references.

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

[4] Boneh, D., & Lipton, R. (1996). A revocable backup system. In *Proceedings of the 6th USENIX Security Symposium* (pp. 91–96). USENIX Association. https://www.usenix.org/legacy/publications/library/proceedings/sec96/full_papers/boneh/boneh.pdf

[5] Botelho, F.C., Shilane, P., Garg, N. and Hsu, W. (2013) ‘Memory efficient sanitization of a deduplicated storage system’, *11th USENIX Conference on File and Storage Technologies (FAST ’13)*. USENIX, pp. 81–94.

[6] Cidre, A. (2026) ‘Don’t delete the row. Delete the key’. Available at: https://adriacidre.com/blog/dont-delete-the-row-delete-the-key/ (Accessed: 19 September 2026).

[7] Douceur, J.R., Adya, A., Bolosky, W.J., Simon, D. and Theimer, M. (2002) ‘Reclaiming space from duplicate files in a serverless distributed file system’, *Proceedings of the 22nd International Conference on Distributed Computing Systems (ICDCS)*. IEEE, pp. 617–624.

[8] Encryption Consulting (2024) ‘Get familiar with the new concept of crypto-shredding’. Available at: https://www.encryptionconsulting.com/introduction-to-crypto-shredding/ (Accessed: 19 September 2026).

[9] European Data Protection Board (2026) *Coordinated Enforcement Action: implementation of the right to erasure by controllers*. Brussels: EDPB.

[10] Fu, Y., Su, J., Ning, J., Wu, J., Lu, Y. and Xiao, N. (2025) ‘Distributed data deduplication for big data: a survey’, *ACM Computing Surveys*, 58(3). doi: 10.1145/3735508.

[11] Information Commissioner’s Office (2023) *Right to erasure*. Available at: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/ (Accessed: 19 September 2026).

[12] myeDPO (2018) ‘Right to erasure (RTBF) from backups’. Available at: https://www.myedpo.com/post/2018/08/21/right-to-erasure-rtbf-from-backups (Accessed: 19 September 2026).

[13] Perlman, R. (2005a). *The ephemerizer: Making data disappear* (Technical Report No. TR-2005-140). Sun Microsystems.

[14] Perlman, R. (2005b). File system design with assured delete. In *Proceedings of the Third IEEE International Security in Storage Workshop* (SISW ’05). IEEE. https://doi.org/10.1109/SISW.2005.5

[15] Peterson, Z. N. J., Burns, R., Herring, J., Stubblefield, A., & Rubin, A. D. (2005). Secure deletion for a versioning file system. In *Proceedings of the 4th USENIX Conference on File and Storage Technologies (FAST ’05)* (pp. 143–154). USENIX Association. https://www.usenix.org/legacy/event/fast05/tech/full_papers/peterson/peterson.pdf

[16] Rahumed, A., Chen, H.C.H., Tang, Y., Lee, P.P.C. and Lui, J.C.S. (2011) ‘A secure cloud backup system with assured deletion and version control’, *International Conference on Parallel Processing Workshops*. IEEE, pp. 160–167.

[17] Tang, Y., Lee, P. P. C., Lui, J. C. S., & Perlman, R. (2010). FADE: Secure overlay cloud storage with file assured deletion. In S. Jajodia & J. Zhou (Eds.), *Security and privacy in communication networks* (pp. 380–397). Springer. https://www.cse.cuhk.edu.hk/~pclee/www/pubs/securecomm10.pdf
